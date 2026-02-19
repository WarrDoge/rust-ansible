//! rust-ansible: Ansible playbook runner using embedded WASIX Python
//!
//! This binary embeds WASIX Python and ansible-core to run playbooks
//! without requiring Python to be installed on the host system.
//!
//! # Architecture
//!
//! 1. Load WASIX Python WASM module
//! 2. Configure WASI environment with:
//!    - Python standard library
//!    - ansible-core and dependencies
//!    - WASI compatibility stubs
//! 3. Mount current directory for playbook access
//! 4. Execute ansible-playbook or ansible ad-hoc commands

use anyhow::{Context, Result};
use clap::Parser;
use std::path::PathBuf;
use std::sync::Arc;
use wasmer::sys::{Features, NativeEngineExt, Target};
use wasmer::{Engine, Module, Store};
use wasmer_wasix::WasiEnv;

/// Command-line arguments for rust-ansible.
#[derive(Parser, Debug)]
#[command(name = "rust-ansible")]
#[command(about = "Run ansible playbooks from a single binary")]
#[command(version)]
struct Args {
    /// Playbook file to run
    playbook: Option<String>,

    /// Inventory file or host list
    #[arg(short, long)]
    inventory: Option<String>,

    /// Module to run (ad-hoc mode)
    #[arg(short, long)]
    module: Option<String>,

    /// Module arguments
    #[arg(short, long)]
    args: Option<String>,

    /// Host pattern (for ad-hoc mode)
    #[arg(default_value = "all")]
    pattern: String,

    /// Increase verbosity (can be repeated)
    #[arg(short, long, action = clap::ArgAction::Count)]
    verbose: u8,

    /// Show ansible version information
    #[arg(long)]
    version: bool,

    /// Path to Python WASM module (for development)
    #[arg(long, env = "RUST_ANSIBLE_PYTHON_WASM")]
    python_wasm: Option<PathBuf>,

    /// Path to Python stdlib directory (for development)
    #[arg(long, env = "RUST_ANSIBLE_PYTHON_LIB")]
    python_lib: Option<PathBuf>,

    /// Path to site-packages directory (for development)
    #[arg(long, env = "RUST_ANSIBLE_SITE_PACKAGES")]
    site_packages: Option<PathBuf>,

    /// Path to stubs directory (for development)
    #[arg(long, env = "RUST_ANSIBLE_STUBS")]
    stubs: Option<PathBuf>,
}

/// Configuration for the WASI runtime environment.
struct WasiConfig {
    python_wasm: PathBuf,
    python_lib: PathBuf,
    site_packages: PathBuf,
    stubs: PathBuf,
}

impl WasiConfig {
    /// Create configuration from CLI args or defaults.
    ///
    /// # Errors
    ///
    /// Returns an error if required paths cannot be determined or don't exist.
    fn from_args(args: &Args) -> Result<Self> {
        // For now, use filesystem paths. Later we'll embed these.
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
            .unwrap_or_else(|| base_dir.join("../feasibility/pysite/.venv/lib/python3.14/site-packages"));

        let stubs = args
            .stubs
            .clone()
            .unwrap_or_else(|| base_dir.join("assets/stubs"));

        // Validate paths exist
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
fn build_python_args(args: &Args) -> Vec<String> {
    // For testing: if pattern starts with "-c", treat it as a Python command
    if args.pattern.starts_with("-c") || args.playbook.as_ref().map_or(false, |p| p == "-c") {
        // Direct Python execution: -c "print('hello')"
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

/// Run WASIX Python with the given configuration.
///
/// # Errors
///
/// Returns an error if:
/// - The WASM module cannot be loaded
/// - The WASI environment cannot be configured
/// - The execution fails
fn run_wasix_python(config: &WasiConfig, python_args: Vec<String>) -> Result<i32> {
    eprintln!("Loading Python WASM module...");

    // Check if we have a pre-compiled module (.wasmu)
    let precompiled_path = config.python_wasm.with_extension("wasmu");

    let (mut store, module, engine) = if precompiled_path.exists() {
        eprintln!("Using pre-compiled module: {}", precompiled_path.display());
        // Use headless engine for pre-compiled modules
        let engine = Engine::headless();
        let store = Store::new(engine.clone());
        // SAFETY: We're loading a module compiled by the same wasmer version
        let module = unsafe {
            Module::deserialize_from_file(&store, &precompiled_path)
                .context("failed to load pre-compiled module")?
        };
        (store, module, engine)
    } else {
        // Compile from source with exception handling support
        eprintln!("Compiling WASM module from source...");
        let wasm_bytes = std::fs::read(&config.python_wasm)
            .with_context(|| format!("failed to read WASM: {}", config.python_wasm.display()))?;

        // Configure Cranelift with exception handling
        let compiler = wasmer_compiler_cranelift::Cranelift::default();
        let engine = Engine::new(
            Box::new(compiler),
            Target::default(),
            Features {
                threads: true,
                reference_types: true,
                simd: true,
                bulk_memory: true,
                multi_value: true,
                tail_call: false,
                module_linking: false,
                multi_memory: false,
                memory64: false,
                exceptions: true, // Required by WASIX Python
                relaxed_simd: false,
                extended_const: false,
            },
        );
        let store = Store::new(engine.clone());
        let module =
            Module::new(&store, &wasm_bytes).context("failed to compile WASM module")?;
        (store, module, engine)
    };

    eprintln!("Configuring WASI environment...");

    // Build PYTHONPATH
    let pythonpath = "/stubs:/site-packages";

    // Get current directory for mounting
    let cwd = std::env::current_dir().context("failed to get current directory")?;
    let home = std::env::var("HOME").unwrap_or_else(|_| "/".to_string());
    let user = std::env::var("USER").unwrap_or_else(|_| "user".to_string());

    eprintln!("  PYTHONPATH: {pythonpath}");
    eprintln!("  Python args: {python_args:?}");

    // Configure WASI environment
    // Map directories:
    // /lib - shared libraries (crypto, sqlite, ssl)
    // /usr - Python stdlib at /usr/local
    // /stubs - our WASI compatibility stubs
    // /site-packages - ansible-core and deps
    // /workspace - current directory for playbooks

    // Create a UnionFileSystem with our mounts
    // This allows the WASM dynamic linker to find shared libraries in /lib
    let union_fs = {
        use virtual_fs::host_fs::FileSystem as HostFs;
        use virtual_fs::union_fs::{MountPoint, UnionFileSystem};

        let handle = tokio::runtime::Handle::current();
        let union = UnionFileSystem::new();

        // Mount /lib -> python stdlib shared libs
        let lib_fs = HostFs::new(handle.clone(), config.python_lib.join("lib"))
            .context("failed to create lib filesystem")?;
        union.mounts.insert(
            PathBuf::from("lib"),
            MountPoint {
                path: PathBuf::from("lib"),
                name: "lib".to_string(),
                fs: Arc::new(Box::new(lib_fs)),
            },
        );

        // Mount /usr -> python stdlib
        let usr_fs = HostFs::new(handle.clone(), config.python_lib.join("usr"))
            .context("failed to create usr filesystem")?;
        union.mounts.insert(
            PathBuf::from("usr"),
            MountPoint {
                path: PathBuf::from("usr"),
                name: "usr".to_string(),
                fs: Arc::new(Box::new(usr_fs)),
            },
        );

        // Mount /stubs -> WASI compatibility stubs
        let stubs_fs = HostFs::new(handle.clone(), &config.stubs)
            .context("failed to create stubs filesystem")?;
        union.mounts.insert(
            PathBuf::from("stubs"),
            MountPoint {
                path: PathBuf::from("stubs"),
                name: "stubs".to_string(),
                fs: Arc::new(Box::new(stubs_fs)),
            },
        );

        // Mount /site-packages -> ansible-core and deps
        let site_fs = HostFs::new(handle.clone(), &config.site_packages)
            .context("failed to create site-packages filesystem")?;
        union.mounts.insert(
            PathBuf::from("site-packages"),
            MountPoint {
                path: PathBuf::from("site-packages"),
                name: "site-packages".to_string(),
                fs: Arc::new(Box::new(site_fs)),
            },
        );

        // Mount /workspace -> current directory
        let workspace_fs = HostFs::new(handle.clone(), &cwd)
            .context("failed to create workspace filesystem")?;
        union.mounts.insert(
            PathBuf::from("workspace"),
            MountPoint {
                path: PathBuf::from("workspace"),
                name: "workspace".to_string(),
                fs: Arc::new(Box::new(workspace_fs)),
            },
        );

        Arc::new(union) as Arc<dyn virtual_fs::FileSystem + Send + Sync>
    };

    // Set HOME to /workspace since that's where playbooks will be
    let builder = WasiEnv::builder("python")
        .args(&python_args)
        .env("PYTHONPATH", pythonpath)
        .env("PYTHONEXECUTABLE", "/bin/python")
        .env("HOME", "/workspace")
        .env("USER", &user)
        .env("TERM", "dumb")
        .env("WASI_BOOTSTRAP", "1")
        .engine(engine)
        .fs(union_fs)
        .preopen_dir("/lib")
        .context("failed to preopen /lib")?
        .preopen_dir("/usr")
        .context("failed to preopen /usr")?
        .preopen_dir("/stubs")
        .context("failed to preopen /stubs")?
        .preopen_dir("/site-packages")
        .context("failed to preopen /site-packages")?
        .preopen_dir("/workspace")
        .context("failed to preopen /workspace")?;

    eprintln!("Starting Python...");

    // Run the module
    let (instance, _env) = builder
        .instantiate(module, &mut store)
        .context("failed to instantiate WASI environment")?;

    let start = instance
        .exports
        .get_function("_start")
        .context("failed to find _start function")?;

    match start.call(&mut store, &[]) {
        Ok(_) => {
            eprintln!("Python exited normally");
            Ok(0)
        }
        Err(e) => {
            // Check if this is a normal exit
            if let Some(exit_code) = e.downcast_ref::<wasmer_wasix::WasiError>() {
                match exit_code {
                    wasmer_wasix::WasiError::Exit(code) => {
                        eprintln!("Python exited with code: {}", code.raw());
                        Ok(code.raw() as i32)
                    }
                    _ => {
                        eprintln!("WASI error: {exit_code:?}");
                        Ok(1)
                    }
                }
            } else {
                eprintln!("Execution error: {e}");
                Ok(1)
            }
        }
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    let args = Args::parse();

    if args.version && args.playbook.is_none() && args.module.is_none() {
        // Quick version without loading Python
        println!("rust-ansible 0.1.0");
        println!("Embedded ansible-core 2.20.2");
        println!("WASIX Python 3.13.0");
        return Ok(());
    }

    // Load configuration
    let config = WasiConfig::from_args(&args)?;

    // Build Python arguments
    let python_args = build_python_args(&args);

    // Run WASIX Python (inside Tokio runtime for wasmer-wasix)
    let exit_code = run_wasix_python(&config, python_args)?;

    std::process::exit(exit_code);
}
