use std::{
    env::{self, home_dir},
    path::PathBuf,
    str::FromStr,
};

use clap::Args;
use hypersdk::hypercore::PrivateKeySigner;

#[derive(Debug, Args)]
pub struct Credentials {
    /// Name of the keystore e.g. `hot_wallet`
    #[arg(short, long)]
    keystore: Option<PathBuf>,
    /// Keystore password. Optional, otherwise prompted.
    #[arg(long)]
    keystore_password: Option<String>,
    /// Raw private key in hex
    #[arg(short, long)]
    private_key: Option<String>,
}

impl Credentials {
    pub fn get(&self) -> anyhow::Result<PrivateKeySigner> {
        if let Some(key) = self.private_key.as_ref() {
            Ok(PrivateKeySigner::from_str(key.as_str())?)
        } else if self.keystore.is_some() {
            match (self.keystore.as_ref(), self.keystore_password.as_ref()) {
                (Some(keystore), Some(password)) => {
                    let path = home_dir()
                        .ok_or(anyhow::anyhow!("unable to find home path"))?
                        .join(".foundry")
                        .join("keystores")
                        .join(keystore);
                    Ok(PrivateKeySigner::decrypt_keystore(path, password)?)
                }
                (Some(keystore), None) => {
                    let path = home_dir()
                        .ok_or(anyhow::anyhow!("unable to find home path"))?
                        .join(".foundry")
                        .join("keystores")
                        .join(keystore);
                    let password = rpassword::prompt_password("Password: ")?;
                    Ok(PrivateKeySigner::decrypt_keystore(path, password)?)
                }
                _ => Err(anyhow::anyhow!(
                    "Missing credentials. Use --private-key or --keystore"
                )),
            }
        } else {
            dotenvy::dotenv()?;
            let private_key = env::var("PRIVATE_KEY")?;
            Ok(PrivateKeySigner::from_str(private_key.as_str())?)
        }
    }
}