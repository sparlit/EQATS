use anyhow::{bail, Result};
use jsonschema::Validator;
use schemars::{schema_for, JsonSchema};
use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, JsonSchema, Debug)]
pub struct DexterResponse {
    pub revenue_impact: String,
    pub primary_catalyst: String,
    #[validate(range(min = -1.0, max = 1.0))]
    pub sentiment_score: f64,
    pub recommended_action: String, // BUY, SELL, HOLD
}

pub struct SchemaValidator {
    compiled_schema: Validator,
}

impl SchemaValidator {
    pub fn new() -> Result<Self> {
        let schema = schema_for!(DexterResponse);
        let schema_value = serde_json::to_value(&schema)?;
        let compiled = jsonschema::validator_for(&schema_value)
            .map_err(|e| anyhow::anyhow!("Schema compilation failed: {}", e))?;
        Ok(Self {
            compiled_schema: compiled,
        })
    }

    pub fn validate_and_parse(&self, llm_json_str: &str) -> Result<DexterResponse> {
        let value: serde_json::Value = serde_json::from_str(llm_json_str)?;

        if self.compiled_schema.validate(&value).is_err() {
            let error_msgs: Vec<String> = self
                .compiled_schema
                .iter_errors(&value)
                .map(|e| e.to_string())
                .collect();
            tracing::error!("Claude returned invalid JSON schema: {:?}", error_msgs);
            bail!("Schema validation failed: {:?}", error_msgs);
        }

        let response: DexterResponse = serde_json::from_value(value)?;
        Ok(response)
    }
}
