// Skill Manager - user-saved favorite skills CRUD.
// Mirrors model_manager.rs structure. File: ~/.echobird/config/skills.json

use std::fs;
use std::time::{SystemTime, UNIX_EPOCH};

use crate::models::skill::{AddSkillInput, SkillConfig, UpdateSkillInput};
use crate::utils::platform::echobird_dir;

/// Skills config file: ~/.echobird/config/skills.json
fn skills_config_path() -> std::path::PathBuf {
    echobird_dir().join("config").join("skills.json")
}

/// Ensure ~/.echobird/config/ exists
fn ensure_config_dir() {
    let config_dir = echobird_dir().join("config");
    let _ = fs::create_dir_all(&config_dir);
}

/// Generate unique skill ID (s-abc123 format)
fn generate_skill_id() -> String {
    let seed = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    format!("s-{:x}", seed % 0xFFFFFF)
}

/// Read all user skills from disk (empty Vec if file missing/corrupt)
pub fn get_skills() -> Vec<SkillConfig> {
    let path = skills_config_path();
    match fs::read_to_string(&path) {
        Ok(content) => serde_json::from_str(&content).unwrap_or_default(),
        Err(_) => Vec::new(),
    }
}

/// Save user skills to disk
fn save_skills(skills: &[SkillConfig]) {
    ensure_config_dir();
    let path = skills_config_path();
    let content = serde_json::to_string_pretty(skills).unwrap_or_default();
    if let Err(e) = fs::write(&path, content) {
        log::error!("[SkillManager] Failed to save skills: {}", e);
    }
}

/// Add a new skill
pub fn add_skill(input: AddSkillInput) -> SkillConfig {
    let mut skills = get_skills();
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();
    let new_skill = SkillConfig {
        id: generate_skill_id(),
        name: input.name.unwrap_or_default(),
        url: input.url.unwrap_or_default(),
        category: input.category.unwrap_or_default(),
        description: input.description.unwrap_or_default(),
        created_at: now,
    };
    log::info!(
        "[SkillManager] Added skill: {} ({})",
        new_skill.name,
        new_skill.id
    );
    skills.push(new_skill.clone());
    save_skills(&skills);
    new_skill
}

/// Delete a skill by ID
pub fn delete_skill(id: &str) -> bool {
    let mut skills = get_skills();
    let original_len = skills.len();
    skills.retain(|s| s.id != id);
    if skills.len() == original_len {
        return false;
    }
    save_skills(&skills);
    log::info!("[SkillManager] Deleted skill: {}", id);
    true
}

/// Update skill fields
pub fn update_skill(id: &str, updates: UpdateSkillInput) -> Option<SkillConfig> {
    let mut skills = get_skills();
    let index = skills.iter().position(|s| s.id == id)?;
    if let Some(name) = updates.name {
        skills[index].name = name;
    }
    if let Some(url) = updates.url {
        skills[index].url = url;
    }
    if let Some(category) = updates.category {
        skills[index].category = category;
    }
    if let Some(description) = updates.description {
        skills[index].description = description;
    }
    let updated = skills[index].clone();
    save_skills(&skills);
    log::info!("[SkillManager] Updated skill: {}", id);
    Some(updated)
}
