//! Shared, read-only Store package resolution. Never starts a shell or a client.

#[derive(Debug, Clone)]
struct Application {
    identity: String,
    aumid: String,
    version: [u16; 4],
}

fn configured_identity(uri: &str) -> Option<(&str, &str)> {
    let aumid = uri
        .strip_prefix("shell:AppsFolder\\")
        .or_else(|| uri.strip_prefix("shell:AppsFolder/"))?;
    let (family, app) = aumid.split_once('!')?;
    let (identity, publisher) = family.rsplit_once('_')?;
    (!identity.is_empty() && !publisher.is_empty() && !app.is_empty()).then_some((identity, app))
}

fn select_application(uri: &str, applications: &[Application]) -> Option<String> {
    let (identity, app_id) = configured_identity(uri)?;
    let beta = format!("{identity}Beta");
    let selected = applications
        .iter()
        .filter(|app| app.identity == identity || app.identity == beta)
        .max_by_key(|app| {
            (
                app.identity == identity,
                app.version,
                app.aumid
                    .rsplit_once('!')
                    .is_some_and(|(_, id)| id == app_id),
            )
        })?;
    Some(format!("shell:AppsFolder\\{}", selected.aumid))
}

#[cfg(windows)]
fn installed_applications(identity: &str) -> windows::core::Result<Vec<Application>> {
    use windows::{core::HSTRING, Management::Deployment::PackageManager};

    let packages = PackageManager::new()?.FindPackagesByUserSecurityId(&HSTRING::new())?;
    let beta = format!("{identity}Beta");
    let mut applications = Vec::new();
    for package in packages {
        let id = package.Id()?;
        let name = id.Name()?.to_string();
        if name != identity && name != beta {
            continue;
        }
        let version = id.Version()?;
        for entry in package.GetAppListEntriesAsync()?.join()? {
            applications.push(Application {
                identity: name.clone(),
                aumid: entry.AppUserModelId()?.to_string(),
                version: [
                    version.Major,
                    version.Minor,
                    version.Build,
                    version.Revision,
                ],
            });
        }
    }
    Ok(applications)
}

#[cfg(windows)]
pub(crate) fn resolve_launch_uri(configured: &str) -> Option<String> {
    let (identity, _) = configured_identity(configured)?;
    match installed_applications(identity) {
        Ok(applications) => select_application(configured, &applications),
        Err(error) => {
            log::warn!("[MSIX] Package lookup failed for {identity}: {error}");
            None
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn app(identity: &str, app_id: &str, version: u16) -> Application {
        Application {
            identity: identity.into(),
            aumid: format!("{identity}_newpublisher!{app_id}"),
            version: [version, 0, 0, 0],
        }
    }

    #[test]
    fn all_store_clients_use_registered_identity_and_application_id() {
        for (identity, app_id) in [
            ("ManusAI.Manus", "ManusApp"),
            ("OpenAI.Codex", "App"),
            ("Claude", "Claude"),
        ] {
            let configured = format!("shell:AppsFolder\\{identity}_oldpublisher!OldApp");
            assert_eq!(
                select_application(&configured, &[app(identity, app_id, 1)]),
                Some(format!(
                    "shell:AppsFolder\\{identity}_newpublisher!{app_id}"
                ))
            );
            // No dependency on an existing per-user data directory, and no
            // installed result based on a stale configured URI alone.
            assert!(select_application(&configured, &[]).is_none());
            assert!(select_application(&configured, &[app("Unrelated", "App", 1)]).is_none());
        }
    }

    #[test]
    fn stable_then_latest_version_then_configured_app_are_preferred() {
        let uri = "shell:AppsFolder\\OpenAI.Codex_old!App";
        let mut apps = vec![app("OpenAI.CodexBeta", "App", 9)];
        assert!(select_application(uri, &apps)
            .unwrap()
            .contains("CodexBeta_"));
        apps.push(app("OpenAI.Codex", "Legacy", 1));
        apps.push(app("OpenAI.Codex", "Other", 2));
        apps.push(app("OpenAI.Codex", "App", 2));
        let expected = Some("shell:AppsFolder\\OpenAI.Codex_newpublisher!App".into());
        assert_eq!(select_application(uri, &apps), expected);
        apps.reverse();
        assert_eq!(select_application(uri, &apps), expected);
    }

    #[test]
    fn malformed_launch_uris_do_not_match_packages() {
        for uri in [
            "",
            "tool.exe",
            "shell:AppsFolder\\Name",
            "shell:AppsFolder\\Name_hash!",
        ] {
            assert!(configured_identity(uri).is_none());
        }
    }

    #[cfg(windows)]
    #[test]
    #[ignore = "live Windows package inventory: requires Microsoft Store installed"]
    fn real_inventory_has_a_positive_control_and_rejects_missing_packages() {
        let apps = installed_applications("Microsoft.WindowsStore").unwrap();
        assert!(
            !apps.is_empty(),
            "positive control must find a registered app"
        );
        assert!(
            resolve_launch_uri("shell:AppsFolder\\Microsoft.WindowsStore_8wekyb3d8bbwe!App")
                .is_some()
        );
        assert!(resolve_launch_uri("shell:AppsFolder\\EchoBird.Nonexistent_test!App").is_none());
    }
}