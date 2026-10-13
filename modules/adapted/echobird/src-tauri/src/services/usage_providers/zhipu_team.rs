//! Per-model organization/project IDs for Zhipu Team quota queries.
//! The inference API key stays in the existing model credential store.
use super::{send_usage_request, zhipu, UsageResult};
use serde::{Deserialize, Serialize};
use std::{collections::HashMap, path::Path, sync::Mutex};

static WRITE_LOCK: Mutex<()> = Mutex::new(());

#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TeamAccess {
    pub organization_id: String,
    pub project_id: String,
}

fn path() -> std::path::PathBuf {
    crate::utils::platform::echobird_dir().join("zhipu_team_access.json")
}

fn read_map(path: &Path) -> Result<HashMap<String, TeamAccess>, String> {
    match std::fs::read(path) {
        Ok(bytes) => serde_json::from_slice(&bytes)
            .map_err(|_| "Invalid team access configuration".to_string()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(HashMap::new()),
        Err(_) => Err("Unable to read team access configuration".to_string()),
    }
}

pub fn read_access(internal_id: &str) -> Result<Option<TeamAccess>, String> {
    Ok(read_map(&path())?.remove(internal_id))
}

fn save_at(path: &Path, internal_id: &str, access: Option<TeamAccess>) -> Result<(), String> {
    let _lock = WRITE_LOCK
        .lock()
        .map_err(|_| "Team access configuration is busy")?;
    let mut map = read_map(path)?;
    if let Some(access) = access {
        if access.organization_id.trim().is_empty() || access.project_id.trim().is_empty() {
            return Err("Organization ID and Project ID are both required".to_string());
        }
        map.insert(
            internal_id.to_string(),
            TeamAccess {
                organization_id: access.organization_id.trim().to_string(),
                project_id: access.project_id.trim().to_string(),
            },
        );
    } else if map.remove(internal_id).is_none() {
        return Ok(());
    }
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let data = serde_json::to_vec(&map).map_err(|error| error.to_string())?;
    let temporary = path.with_extension("tmp");
    std::fs::write(&temporary, data).map_err(|error| error.to_string())?;
    std::fs::rename(temporary, path).map_err(|error| error.to_string())
}

pub fn save_access(internal_id: &str, access: Option<TeamAccess>) -> Result<(), String> {
    save_at(&path(), internal_id, access)
}

fn request(api_key: &str, access: &TeamAccess) -> reqwest::RequestBuilder {
    reqwest::Client::new()
        .get("https://open.bigmodel.cn/api/monitor/usage/quota/limit?type=2")
        .header("Authorization", api_key)
        .header("bigmodel-organization", &access.organization_id)
        .header("bigmodel-project", &access.project_id)
}

pub async fn query_usage(api_key: &str, access: &TeamAccess) -> Result<UsageResult, String> {
    Ok(match send_usage_request(request(api_key, access)).await {
        Ok(body) => zhipu::parse_response(&body),
        Err(error) => UsageResult::failure(error),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn team_query_uses_raw_key_and_both_account_identifiers() {
        let access = TeamAccess {
            organization_id: "org-test".into(),
            project_id: "project-test".into(),
        };
        let request = request("test-key", &access).build().unwrap();
        assert_eq!(
            request.url().as_str(),
            "https://open.bigmodel.cn/api/monitor/usage/quota/limit?type=2"
        );
        assert_eq!(request.headers()["Authorization"], "test-key");
        assert_eq!(request.headers()["bigmodel-organization"], "org-test");
        assert_eq!(request.headers()["bigmodel-project"], "project-test");
    }

    #[test]
    fn saving_and_clearing_preserves_other_models_and_corrupt_files() {
        let dir = std::env::temp_dir().join(format!("echobird-team-{}", uuid::Uuid::new_v4()));
        let file = dir.join("access.json");
        let access = TeamAccess {
            organization_id: "org".into(),
            project_id: "project".into(),
        };
        save_at(&file, "one", Some(access.clone())).unwrap();
        save_at(&file, "two", Some(access)).unwrap();
        save_at(&file, "one", None).unwrap();
        let map = read_map(&file).unwrap();
        assert!(map.contains_key("two"));
        assert!(!map.contains_key("one"));
        std::fs::write(&file, b"broken").unwrap();
        assert!(save_at(&file, "two", None).is_err());
        assert_eq!(std::fs::read(&file).unwrap(), b"broken");
        std::fs::remove_dir_all(dir).unwrap();
    }
}