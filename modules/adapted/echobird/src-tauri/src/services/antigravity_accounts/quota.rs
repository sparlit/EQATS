use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::time::Duration;

pub(super) const CLIENT_ID: &str = match option_env!("ANTIGRAVITY_OAUTH_CLIENT_ID") {
    Some(value) => value,
    None => "",
};
pub(super) const CLIENT_SECRET: &str = match option_env!("ANTIGRAVITY_OAUTH_CLIENT_SECRET") {
    Some(value) => value,
    None => "",
};
const BASE: &str = "https://daily-cloudcode-pa.googleapis.com/v1internal:";

#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ModelQuota {
    pub name: String,
    pub remaining_percent: f64,
    pub reset_at: Option<i64>,
}

fn model_quota(name: &str, info: &Value) -> Option<ModelQuota> {
    let fraction = info["quotaInfo"]["remainingFraction"].as_f64()?;
    if !fraction.is_finite() || !(0.0..=1.0).contains(&fraction) {
        return None;
    }
    let reset_at = info["quotaInfo"]["resetTime"]
        .as_str()
        .and_then(|s| chrono::DateTime::parse_from_rfc3339(s).ok())
        .map(|dt| dt.timestamp());
    Some(ModelQuota {
        name: name.to_owned(),
        remaining_percent: fraction * 100.0,
        reset_at,
    })
}

fn client() -> Result<reqwest::Client, String> {
    reqwest::Client::builder()
        .timeout(Duration::from_secs(15))
        .build()
        .map_err(|_| "accountError.network".into())
}

async fn post(token: &str, path: &str, body: Value) -> Result<Value, String> {
    let response = client()?
        .post(format!("{BASE}{path}"))
        .bearer_auth(token)
        .header(
            "User-Agent",
            format!(
                "antigravity/{} {}/{}",
                "2.19.1",
                std::env::consts::OS,
                std::env::consts::ARCH
            ),
        )
        .json(&body)
        .send()
        .await
        .map_err(|_| "accountError.network")?;
    if !response.status().is_success() {
        return Err(format!(
            "accountError.auth|HTTP {}",
            response.status().as_u16()
        ));
    }
    response
        .json()
        .await
        .map_err(|_| "accountError.authResponse".into())
}

pub(super) async fn refresh_access(secret: &mut Value) -> Result<(), String> {
    let expires = secret["token"]["expiry"]
        .as_str()
        .and_then(|s| chrono::DateTime::parse_from_rfc3339(s).ok())
        .map(|dt| dt.timestamp())
        .unwrap_or(0);
    if expires > chrono::Utc::now().timestamp() + 120 {
        return Ok(());
    }
    let refresh_token = secret["token"]["refresh_token"]
        .as_str()
        .filter(|s| !s.is_empty())
        .ok_or("accountError.invalidAccount")?;
    let response = client()?
        .post("https://oauth2.googleapis.com/token")
        .form(&[
            ("client_id", CLIENT_ID),
            ("client_secret", CLIENT_SECRET),
            ("refresh_token", refresh_token),
            ("grant_type", "refresh_token"),
        ])
        .send()
        .await
        .map_err(|_| "accountError.network")?;
    if !response.status().is_success() {
        return Err(format!(
            "accountError.auth|HTTP {}",
            response.status().as_u16()
        ));
    }
    let result: Value = response
        .json()
        .await
        .map_err(|_| "accountError.authResponse")?;
    let access = result["access_token"]
        .as_str()
        .filter(|s| !s.is_empty())
        .ok_or("accountError.authResponse")?;
    secret["token"]["access_token"] = json!(access);
    if let Some(token) = result["id_token"].as_str() {
        secret["id_token"] = json!(token);
    }
    if let Some(token) = result["refresh_token"].as_str().filter(|s| !s.is_empty()) {
        secret["token"]["refresh_token"] = json!(token);
    }
    let expires_in = result["expires_in"].as_i64().unwrap_or(3600);
    secret["token"]["expiry"] =
        json!((chrono::Utc::now() + chrono::Duration::seconds(expires_in)).to_rfc3339());
    Ok(())
}

pub(super) async fn fetch(secret: &Value) -> Result<(Option<String>, Vec<ModelQuota>), String> {
    let token = secret["token"]["access_token"]
        .as_str()
        .filter(|s| !s.is_empty())
        .ok_or("accountError.invalidAccount")?;
    let version = "2.19.1";
    let os = match std::env::consts::OS {
        "macos" => "DARWIN",
        "linux" => "LINUX",
        _ => "WINDOWS",
    };
    let arch = match std::env::consts::ARCH {
        "aarch64" => "ARM64",
        _ => "AMD64",
    };
    let metadata = json!({
        "ideName": "antigravity", "ideType": "ANTIGRAVITY",
        "ideVersion": version, "platform": format!("{os}_{arch}"),
        "updateChannel": "stable", "pluginType": "GEMINI"
    });
    let tiers = post(
        token,
        "loadCodeAssist",
        json!({"metadata":metadata,"mode":"FULL_ELIGIBILITY_CHECK"}),
    )
    .await?;
    let tier_id = tiers["paidTier"]["id"]
        .as_str()
        .or_else(|| tiers["currentTier"]["id"].as_str());
    let plan = tier_id.and_then(|id| {
        let id = id.to_ascii_lowercase();
        if id.contains("ultra") {
            Some("Ultra".to_string())
        } else if id.contains("pro") {
            Some("Pro".to_string())
        } else if id.contains("plus") {
            Some("Plus".to_string())
        } else if id.contains("free") {
            Some("Free".to_string())
        } else {
            None
        }
    });
    let project = tiers["cloudaicompanionProject"]
        .as_str()
        .or_else(|| tiers["cloudaicompanionProject"]["id"].as_str());
    let body = project.map_or_else(|| json!({}), |p| json!({"project":p}));
    let models = post(token, "fetchAvailableModels", body).await?;
    let quotas = models["models"]
        .as_object()
        .ok_or("accountError.authResponse")?
        .iter()
        .filter_map(|(name, info)| model_quota(name, info))
        .collect();
    Ok((plan, quotas))
}

#[cfg(test)]
mod tests {
    use super::model_quota;

    #[test]
    fn parses_real_fraction_and_skips_missing_or_invalid_quota() {
        let response = serde_json::json!({"quotaInfo":{"remainingFraction":0.25,"resetTime":"2026-10-01T12:00:00Z"}});
        let parsed = model_quota("gemini-3", &response).unwrap();
        assert_eq!(parsed.remaining_percent, 25.0);
        assert_eq!(parsed.reset_at, Some(1790856000));
        assert!(model_quota("claude", &serde_json::json!({"quotaInfo":{}})).is_none());
        assert!(model_quota(
            "claude",
            &serde_json::json!({"quotaInfo":{"remainingFraction":1.5}})
        )
        .is_none());
    }
}