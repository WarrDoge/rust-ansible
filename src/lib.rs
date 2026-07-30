//! rust-ansible: Ansible playbook runner using embedded WASIX Python
//!
//! This library crate exposes the testable non-runtime logic:
//! CLI argument parsing, path resolution, and configuration validation.

use anyhow::{Context, Result};
use clap::Parser;
use std::path::PathBuf;

/// Command-line arguments for rust-ansible.
#[derive(Parser, Debug)]
#[command(name = "rust-ansible")]
#[command(about = "Run ansible playbooks from a single binary")]
pub struct Args {
    /// Playbook file to run
    pub playbook: Option<String>,

    /// Inventory file or host list
    #[arg(short, long)]
    pub inventory: Option<String>,

    /// Module to run (ad-hoc mode)
    #[arg(short, long)]
    pub module: Option<String>,

    /// Module arguments
    #[arg(short, long)]
    pub args: Option<String>,

    /// Host pattern (for ad-hoc mode)
    #[arg(default_value = "all")]
    pub pattern: String,

    /// Increase verbosity (can be repeated)
    #[arg(short, long, action = clap::ArgAction::Count)]
    pub verbose: u8,

    /// Show ansible version information
    #[arg(long)]
    pub version: bool,

    /// Path to Python WASM module (for development)
    #[arg(long, env = "RUST_ANSIBLE_PYTHON_WASM")]
    pub python_wasm: Option<PathBuf>,

    /// Path to Python stdlib directory (for development)
    #[arg(long, env = "RUST_ANSIBLE_PYTHON_LIB")]
    pub python_lib: Option<PathBuf>,

    /// Path to site-packages directory (for development)
    #[arg(long, env = "RUST_ANSIBLE_SITE_PACKAGES")]
    pub site_packages: Option<PathBuf>,

    /// Path to stubs directory (for development)
    #[arg(long, env = "RUST_ANSIBLE_STUBS")]
    pub stubs: Option<PathBuf>,
}

/// Configuration for the WASI runtime environment.
#[derive(Debug)]
pub struct WasiConfig {
    pub python_wasm: PathBuf,
    pub python_lib: PathBuf,
    pub site_packages: PathBuf,
    pub stubs: PathBuf,
}

impl WasiConfig {
    /// Create configuration from CLI args or defaults.
    ///
    /// All paths must be supplied via CLI flags or environment variables.
    /// Falls back to sensible defaults for development use.
    ///
    /// # Errors
    ///
    /// Returns an error if the Python WASM module cannot be found.
    pub fn from_args(args: &Args) -> Result<Self> {
        let base_dir = std::env::current_dir().context("failed to get current directory")?;

        let python_wasm = args
            .python_wasm
            .clone()
            .unwrap_or_else(|| PathBuf::from("/tmp/python_unpacked/python"));

        let python_lib = args
            .python_lib
            .clone()
            .unwrap_or_else(|| PathBuf::from("/tmp/python_unpacked/root"));

        let site_packages = args
            .site_packages
            .clone()
            .ok_or_else(|| {
                anyhow::anyhow!(
                    "site-packages path required.\n\
                     Set --site-packages or RUST_ANSIBLE_SITE_PACKAGES"
                )
            })?;

        let stubs = args
            .stubs
            .clone()
            .unwrap_or_else(|| base_dir.join("assets/stubs"));

        if !python_wasm.exists() {
            anyhow::bail!(
                "Python WASM not found at: {}\n\
                 Run: wasmer package download python/python -o /tmp/python.webc && \
                 wasmer package unpack --format webc -o /tmp/python_unpacked /tmp/python.webc",
                python_wasm.display()
            );
        }

        Ok(Self {
            python_wasm,
            python_lib,
            site_packages,
            stubs,
        })
    }
}

/// Build Python arguments for ansible execution.
pub fn build_python_args(args: &Args) -> Vec<String> {
    // Direct Python execution: -c "print('hello')"
    if args.pattern.starts_with("-c") || args.playbook.as_ref().map_or(false, |p| p == "-c") {
        let code = args.playbook.as_ref().map_or(&args.pattern, |p| {
            if p == "-c" {
                &args.pattern
            } else {
                p
            }
        });
        return vec!["-c".to_string(), code.clone()];
    }

    let mut python_args = vec!["-m".to_string()];

    if args.module.is_some() {
        // Ad-hoc mode: ansible -m module -a args pattern
        python_args.push("ansible".to_string());
        if let Some(ref inv) = args.inventory {
            python_args.extend(["-i".to_string(), inv.clone()]);
        }
        if let Some(ref module) = args.module {
            python_args.extend(["-m".to_string(), module.clone()]);
        }
        if let Some(ref module_args) = args.args {
            python_args.extend(["-a".to_string(), module_args.clone()]);
        }
        for _ in 0..args.verbose {
            python_args.push("-v".to_string());
        }
        python_args.push(args.pattern.clone());
    } else if let Some(ref playbook) = args.playbook {
        // Playbook mode
        python_args.push("ansible.cli.playbook".to_string());
        if let Some(ref inv) = args.inventory {
            python_args.extend(["-i".to_string(), inv.clone()]);
        }
        for _ in 0..args.verbose {
            python_args.push("-v".to_string());
        }
        python_args.push(playbook.clone());
    } else if args.version {
        python_args.extend(["ansible.cli.playbook".to_string(), "--version".to_string()]);
    } else {
        python_args.extend(["ansible.cli.playbook".to_string(), "--help".to_string()]);
    }

    python_args
}

#[cfg(test)]
mod tests {
    use super::*;
    use clap::CommandFactory;

    // -----------------------------------------------------------------------
    // CLI argument parsing
    // -----------------------------------------------------------------------

    #[test]
    fn test_args_playbook_only() {
        let args = Args::try_parse_from(["rust-ansible", "playbook.yml"]).unwrap();
        assert_eq!(args.playbook, Some("playbook.yml".to_string()));
        assert_eq!(args.pattern, "all");
        assert_eq!(args.verbose, 0);
        assert!(!args.version);
        assert!(args.inventory.is_none());
        assert!(args.module.is_none());
    }

    #[test]
    fn test_args_with_inventory_and_verbose() {
        let args = Args::try_parse_from([
            "rust-ansible", "-i", "hosts.ini", "-vvv", "site.yml",
        ])
        .unwrap();
        assert_eq!(args.playbook, Some("site.yml".to_string()));
        assert_eq!(args.inventory, Some("hosts.ini".to_string()));
        assert_eq!(args.verbose, 3);
    }

    #[test]
    fn test_args_ad_hoc_module() {
        let args = Args::try_parse_from([
            "rust-ansible", "-m", "ping", "-a", "data=ok", "webservers",
        ])
        .unwrap();
        assert_eq!(args.module, Some("ping".to_string()));
        assert_eq!(args.args, Some("data=ok".to_string()));
        // "webservers" is the first positional (playbook) not pattern
        assert_eq!(args.playbook, Some("webservers".to_string()));
        assert_eq!(args.pattern, "all");
    }

    #[test]
    fn test_args_version_flag() {
        let args = Args::try_parse_from(["rust-ansible", "--version"]).unwrap();
        assert!(args.version);
        assert!(args.playbook.is_none());
        assert!(args.module.is_none());
    }

    #[test]
    fn test_args_default_pattern() {
        let args = Args::try_parse_from(["rust-ansible", "play.yml", "-m", "ping"]).unwrap();
        assert_eq!(args.playbook, Some("play.yml".to_string()));
        // When playbook is set AND module is set, pattern is the playbook.
        // The "ad-hoc" path checks args.module.is_some() first.
        assert_eq!(args.pattern, "all");
    }

    #[test]
    fn test_args_verbose_count() {
        let args = Args::try_parse_from(["rust-ansible", "play.yml", "-v"]).unwrap();
        assert_eq!(args.verbose, 1);

        let args = Args::try_parse_from(["rust-ansible", "play.yml", "-vvvv"]).unwrap();
        assert_eq!(args.verbose, 4);
    }

    #[test]
    fn test_args_custom_paths() {
        let args = Args::try_parse_from([
            "rust-ansible",
            "--python-wasm",
            "/opt/wasm/python",
            "--python-lib",
            "/opt/wasm/lib",
            "--site-packages",
            "/opt/wasm/site-packages",
            "--stubs",
            "/opt/wasm/stubs",
            "play.yml",
        ])
        .unwrap();
        assert_eq!(
            args.python_wasm,
            Some(PathBuf::from("/opt/wasm/python"))
        );
        assert_eq!(args.python_lib, Some(PathBuf::from("/opt/wasm/lib")));
        assert_eq!(
            args.site_packages,
            Some(PathBuf::from("/opt/wasm/site-packages"))
        );
        assert_eq!(args.stubs, Some(PathBuf::from("/opt/wasm/stubs")));
    }

    #[test]
    fn test_args_requires_at_least_playbook_or_module() {
        // With nothing, clap produces defaults (pattern="all", no playbook, no module)
        // This is a valid parse — the app runtime handles the "no playbook" case.
        let args = Args::try_parse_from(["rust-ansible"]).unwrap();
        assert!(args.playbook.is_none());
        assert!(args.module.is_none());
        assert_eq!(args.pattern, "all");
    }

    #[test]
    fn test_args_unknown_flag_errors() {
        let result = Args::try_parse_from(["rust-ansible", "--bogus"]);
        assert!(result.is_err());
    }

    #[test]
    fn test_args_help() {
        // Verify Clap CommandFactory works
        let mut cmd = Args::command();
        let help = cmd.render_help().to_string();
        assert!(help.contains("rust-ansible"));
        assert!(help.contains("playbook"));
        assert!(help.contains("--inventory"));
    }

    #[test]
    fn test_args_playbook_and_inventory() {
        let args = Args::try_parse_from([
            "rust-ansible", "deploy.yml", "-i", "prod.ini",
        ])
        .unwrap();
        assert_eq!(args.playbook, Some("deploy.yml".to_string()));
        assert_eq!(args.inventory, Some("prod.ini".to_string()));
    }

    // -----------------------------------------------------------------------
    // build_python_args
    // -----------------------------------------------------------------------

    #[test]
    fn test_build_python_args_playbook_mode() {
        let args = Args {
            playbook: Some("site.yml".to_string()),
            inventory: Some("hosts.ini".to_string()),
            module: None,
            args: None,
            pattern: "all".to_string(),
            verbose: 1,
            version: false,
            python_wasm: None,
            python_lib: None,
            site_packages: None,
            stubs: None,
        };
        let py_args = build_python_args(&args);
        assert_eq!(
            py_args,
            vec![
                "-m",
                "ansible.cli.playbook",
                "-i",
                "hosts.ini",
                "-v",
                "site.yml",
            ]
        );
    }

    #[test]
    fn test_build_python_args_playbook_no_inventory_no_verbose() {
        let args = Args {
            playbook: Some("site.yml".to_string()),
            inventory: None,
            module: None,
            args: None,
            pattern: "all".to_string(),
            verbose: 0,
            version: false,
            python_wasm: None,
            python_lib: None,
            site_packages: None,
            stubs: None,
        };
        let py_args = build_python_args(&args);
        assert_eq!(py_args, vec!["-m", "ansible.cli.playbook", "site.yml"]);
    }

    #[test]
    fn test_build_python_args_ad_hoc() {
        let args = Args {
            playbook: None,
            inventory: Some("hosts.ini".to_string()),
            module: Some("ping".to_string()),
            args: Some("data=ok".to_string()),
            pattern: "webservers".to_string(),
            verbose: 0,
            version: false,
            python_wasm: None,
            python_lib: None,
            site_packages: None,
            stubs: None,
        };
        let py_args = build_python_args(&args);
        assert_eq!(
            py_args,
            vec![
                "-m",
                "ansible",
                "-i",
                "hosts.ini",
                "-m",
                "ping",
                "-a",
                "data=ok",
                "webservers",
            ]
        );
    }

    #[test]
    fn test_build_python_args_ad_hoc_no_inventory() {
        let args = Args {
            playbook: None,
            inventory: None,
            module: Some("shell".to_string()),
            args: Some("uptime".to_string()),
            pattern: "all".to_string(),
            verbose: 2,
            version: false,
            python_wasm: None,
            python_lib: None,
            site_packages: None,
            stubs: None,
        };
        let py_args = build_python_args(&args);
        assert_eq!(
            py_args,
            vec!["-m", "ansible", "-m", "shell", "-a", "uptime", "-v", "-v", "all"]
        );
    }

    #[test]
    fn test_build_python_args_version() {
        let args = Args {
            playbook: None,
            inventory: None,
            module: None,
            args: None,
            pattern: "all".to_string(),
            verbose: 0,
            version: true,
            python_wasm: None,
            python_lib: None,
            site_packages: None,
            stubs: None,
        };
        let py_args = build_python_args(&args);
        assert_eq!(
            py_args,
            vec!["-m", "ansible.cli.playbook", "--version"]
        );
    }

    #[test]
    fn test_build_python_args_help_default() {
        let args = Args {
            playbook: None,
            inventory: None,
            module: None,
            args: None,
            pattern: "all".to_string(),
            verbose: 0,
            version: false,
            python_wasm: None,
            python_lib: None,
            site_packages: None,
            stubs: None,
        };
        let py_args = build_python_args(&args);
        assert_eq!(
            py_args,
            vec!["-m", "ansible.cli.playbook", "--help"]
        );
    }

    #[test]
    fn test_build_python_args_direct_execution() {
        let args = Args {
            playbook: Some("-c".to_string()),
            inventory: None,
            module: None,
            args: None,
            pattern: "print('hello')".to_string(),
            verbose: 0,
            version: false,
            python_wasm: None,
            python_lib: None,
            site_packages: None,
            stubs: None,
        };
        let py_args = build_python_args(&args);
        assert_eq!(py_args, vec!["-c", "print('hello')"]);
    }

    #[test]
    fn test_build_python_args_direct_execution_via_pattern() {
        let args = Args {
            playbook: None,
            inventory: None,
            module: None,
            args: None,
            pattern: "-c print('hi')".to_string(),
            verbose: 0,
            version: false,
            python_wasm: None,
            python_lib: None,
            site_packages: None,
            stubs: None,
        };
        let py_args = build_python_args(&args);
        assert_eq!(py_args, vec!["-c", "-c print('hi')"]);
    }

    #[test]
    fn test_build_python_args_verbose_in_ad_hoc() {
        let args = Args {
            playbook: Some("playbook.yml".to_string()),
            inventory: Some("inv.ini".to_string()),
            module: Some("debug".to_string()),
            args: Some("msg=test".to_string()),
            pattern: "all".to_string(),
            verbose: 3,
            version: false,
            python_wasm: None,
            python_lib: None,
            site_packages: None,
            stubs: None,
        };
        let py_args = build_python_args(&args);
        // When module is Some, ad-hoc path is taken even if playbook is also set
        assert_eq!(py_args[0], "-m");
        assert_eq!(py_args[1], "ansible");
        assert!(py_args.contains(&"-v".to_string()));
        // Three -v flags for verbose=3
        let v_count = py_args.iter().filter(|s| *s == "-v").count();
        assert_eq!(v_count, 3);
    }

    // -----------------------------------------------------------------------
    // WasiConfig::from_args
    // -----------------------------------------------------------------------

    #[test]
    fn test_wasi_config_requires_site_packages() {
        let args = Args {
            playbook: None,
            inventory: None,
            module: None,
            args: None,
            pattern: "all".to_string(),
            verbose: 0,
            version: false,
            python_wasm: Some(PathBuf::from("/tmp/nonexistent/python_wasm")),
            python_lib: Some(PathBuf::from("/tmp/nonexistent/python_lib")),
            site_packages: None,
            stubs: Some(PathBuf::from("/tmp/nonexistent/stubs")),
        };
        let result = WasiConfig::from_args(&args);
        assert!(result.is_err());
        let err = result.unwrap_err().to_string();
        assert!(err.contains("site-packages"), "error should mention site-packages: {err}");
    }

    #[test]
    fn test_wasi_config_requires_existing_wasm() {
        let args = Args {
            playbook: None,
            inventory: None,
            module: None,
            args: None,
            pattern: "all".to_string(),
            verbose: 0,
            version: false,
            python_wasm: Some(PathBuf::from("/tmp/nonexistent_wasm_file.wasm")),
            python_lib: Some(PathBuf::from("/tmp/nonexistent_lib")),
            site_packages: Some(PathBuf::from("/tmp/nonexistent_site")),
            stubs: Some(PathBuf::from("/tmp/nonexistent_stubs")),
        };
        let result = WasiConfig::from_args(&args);
        assert!(result.is_err());
        let err = result.unwrap_err().to_string();
        assert!(err.contains("Python WASM not found"), "error should mention WASM not found: {err}");
    }

    #[test]
    fn test_wasi_config_with_valid_paths() {
        // Create temp files to make .exists() pass
        let dir = std::env::temp_dir().join(format!("rust_ansible_test_{}", std::process::id()));
        let _ = std::fs::create_dir_all(&dir);
        let wasm_path = dir.join("python");
        let lib_path = dir.join("root");
        let site_path = dir.join("site-packages");
        let stubs_path = dir.join("stubs");
        std::fs::write(&wasm_path, b"dummy wasm").ok();
        std::fs::create_dir_all(&lib_path).ok();
        std::fs::create_dir_all(&site_path).ok();
        std::fs::create_dir_all(&stubs_path).ok();

        let args = Args {
            playbook: None,
            inventory: None,
            module: None,
            args: None,
            pattern: "all".to_string(),
            verbose: 0,
            version: false,
            python_wasm: Some(wasm_path.clone()),
            python_lib: Some(lib_path.clone()),
            site_packages: Some(site_path.clone()),
            stubs: Some(stubs_path.clone()),
        };
        let config = WasiConfig::from_args(&args).unwrap();
        assert_eq!(config.python_wasm, wasm_path);
        assert_eq!(config.python_lib, lib_path);
        assert_eq!(config.site_packages, site_path);
        assert_eq!(config.stubs, stubs_path);

        // Cleanup
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn test_wasi_config_defaults_when_args_missing() {
        // site_packages is required, so we test that defaults work for other fields
        let dir = std::env::temp_dir().join(format!("rust_ansible_test_defaults_{}", std::process::id()));
        let _ = std::fs::create_dir_all(&dir);
        let wasm_path = dir.join("python");
        let site_path = dir.join("site-packages");
        std::fs::write(&wasm_path, b"dummy").ok();
        std::fs::create_dir_all(&site_path).ok();

        let args = Args {
            playbook: None,
            inventory: None,
            module: None,
            args: None,
            pattern: "all".to_string(),
            verbose: 0,
            version: false,
            python_wasm: Some(wasm_path.clone()),
            python_lib: None,  // should default to /tmp/python_unpacked/root
            site_packages: Some(site_path),
            stubs: None,  // should default to cwd/assets/stubs
        };
        let config = WasiConfig::from_args(&args).unwrap();
        assert_eq!(config.python_lib, PathBuf::from("/tmp/python_unpacked/root"));
        // stubs defaults to current_dir/assets/stubs
        let cwd = std::env::current_dir().unwrap();
        assert_eq!(config.stubs, cwd.join("assets/stubs"));

        let _ = std::fs::remove_dir_all(&dir);
    }
}
