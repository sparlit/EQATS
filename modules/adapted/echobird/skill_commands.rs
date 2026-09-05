// Tauri Commands for skill (favorite) operations - exposed to frontend via invoke()

use crate::models::skill::{AddSkillInput, SkillConfig, UpdateSkillInput};
use crate::services::skill_manager;

/// Get all user-saved skills
#[tauri::command]
pub fn get_skills() -> Vec<SkillConfig> {
    skill_manager::get_skills()
}

/// Add a new skill
#[tauri::command]
pub fn add_skill(input: AddSkillInput) -> SkillConfig {
    skill_manager::add_skill(input)
}

/// Delete a skill by ID
#[tauri::command]
pub fn delete_skill(id: String) -> bool {
    skill_manager::delete_skill(&id)
}

/// Update a skill
#[tauri::command]
pub fn update_skill(id: String, updates: UpdateSkillInput) -> Option<SkillConfig> {
    skill_manager::update_skill(&id, updates)
}
