// User-saved skill (favorite) structures - stored in ~/.echobird/config/skills.json

use serde::{Deserialize, Serialize};

/// A user-saved skill (favorite). Stored in ~/.echobird/config/skills.json.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SkillConfig {
    pub id: String,
    pub name: String,
    pub url: String,
    pub category: String,
    #[serde(default)]
    pub description: String,
    pub created_at: u64,
}

/// Add skill input (from frontend)
#[derive(Debug, Default, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AddSkillInput {
    #[serde(default)]
    pub name: Option<String>,
    #[serde(default)]
    pub url: Option<String>,
    #[serde(default)]
    pub category: Option<String>,
    #[serde(default)]
    pub description: Option<String>,
}

/// Update skill input (all fields optional)
#[derive(Debug, Default, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateSkillInput {
    #[serde(default)]
    pub name: Option<String>,
    #[serde(default)]
    pub url: Option<String>,
    #[serde(default)]
    pub category: Option<String>,
    #[serde(default)]
    pub description: Option<String>,
}