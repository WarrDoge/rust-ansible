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
use std::path::{Path, PathBuf};
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
    /// All paths must be supplied via CLI flags or environment variables.
    /// Falls back to sensible defaults for development use.
    ///
    /// # Errors
    ///
    /// Returns an error if the Python WASM module cannot be found.
    fn from_args(args: &Args) -> Result<Self> {
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
fn build_python_args(args: &Args) -> Vec<String> {
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

/// Add a host filesystem mount to the union filesystem.
fn add_mount(
    union: &virtual_fs::union_fs::UnionFileSystem,
    handle: &tokio::runtime::Handle,
    host_path: &Path,
    mount_name: &str,
) -> Result<()> {
    use virtual_fs::host_fs::FileSystem as HostFs;
    use virtual_fs::union_fs::MountPoint;

    let fs = HostFs::new(handle.clone(), host_path)
        .with_context(|| format!("failed to create {mount_name} filesystem"))?;

    union.mounts.insert(
        PathBuf::from(mount_name),
        MountPoint {
            path: PathBuf::from(mount_name),
            name: mount_name.to_string(),
            fs: Arc::new(Box::new(fs)),
        },
    );

    Ok(())
}

/// Run WASIX Python with the given configuration.
///
/// # Errors
///
/// Returns an error if:
/// - The WASM module cannot be loaded
/// - The WASI environment cannot be configured
/// - The execution fails unexpectedly
fn run_wasix_python(config: &WasiConfig, python_args: Vec<String>, verbose: u8) -> Result<i32> {
    if verbose > 0 {
        eprintln!("Loading Python WASM module...");
    }

    // Check if we have a pre-compiled module (.wasmu)
    let precompiled_path = config.python_wasm.with_extension("wasmu");

    let (mut store, module, engine) = if precompiled_path.exists() {
        if verbose > 0 {
            eprintln!("Using pre-compiled module: {}", precompiled_path.display());
        }
        let engine = Engine::headless();
        let store = Store::new(engine.clone());
        // SAFETY: We're loading a module compiled by the same wasmer version
        let module = unsafe {
            Module::deserialize_from_file(&store, &precompiled_path)
                .context("failed to load pre-compiled module")?
        };
        (store, module, engine)
    } else {
        if verbose > 0 {
            eprintln!("Compiling WASM module from source...");
        }
        let wasm_bytes = std::fs::read(&config.python_wasm)
            .with_context(|| format!("failed to read WASM: {}", config.python_wasm.display()))?;

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

    if verbose > 0 {
        eprintln!("Configuring WASI environment...");
    }

    let pythonpath = "/stubs:/site-packages";
    let cwd = std::env::current_dir().context("failed to get current directory")?;
    let user = std::env::var("USER").unwrap_or_else(|_| "user".to_string());

    if verbose > 1 {
        eprintln!("  PYTHONPATH: {pythonpath}");
        eprintln!("  Python args: {python_args:?}");
    }

    // Build union filesystem with all required mounts:
    //   /lib            - shared libraries (crypto, sqlite, ssl)
    //   /usr            - Python stdlib at /usr/local
    //   /stubs          - WASI compatibility stubs
    //   /site-packages  - ansible-core and deps
    //   /workspace      - current directory for playbooks
    let union_fs = {
        use virtual_fs::union_fs::UnionFileSystem;

        let handle = tokio::runtime::Handle::current();
        let union = UnionFileSystem::new();

        add_mount(&union, &handle, &config.python_lib.join("lib"), "lib")?;
        add_mount(&union, &handle, &config.python_lib.join("usr"), "usr")?;
        add_mount(&union, &handle, &config.stubs, "stubs")?;
        add_mount(&union, &handle, &config.site_packages, "site-packages")?;
        add_mount(&union, &handle, &cwd, "workspace")?;

        Arc::new(union) as Arc<dyn virtual_fs::FileSystem + Send + Sync>
    };

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

    if verbose > 0 {
        eprintln!("Starting Python...");
    }

    let (instance, _env) = builder
        .instantiate(module, &mut store)
        .context("failed to instantiate WASI environment")?;

    let start = instance
        .exports
        .get_function("_start")
        .context("failed to find _start function")?;

    match start.call(&mut store, &[]) {
        Ok(_) => {
            if verbose > 0 {
                eprintln!("Python exited normally");
            }
            Ok(0)
        }
        Err(e) => {
            if let Some(exit_code) = e.downcast_ref::<wasmer_wasix::WasiError>() {
                match exit_code {
                    wasmer_wasix::WasiError::Exit(code) => {
                        if verbose > 0 {
                            eprintln!("Python exited with code: {}", code.raw());
                        }
                        Ok(code.raw() as i32)
                    }
                    _ => {
                        eprintln!("WASI error: {exit_code:?}");
                        Ok(1)
                    }
                }
            } else {
                Err(e).context("unexpected execution error in WASM module")
            }
        }
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    let args = Args::parse();

    if args.version && args.playbook.is_none() && args.module.is_none() {
        println!("rust-ansible 0.1.0");
        println!("Embedded ansible-core 2.20.2");
        println!("WASIX Python 3.13.0");
        return Ok(());
    }

    let config = WasiConfig::from_args(&args)?;
    let python_args = build_python_args(&args);

    // Run WASIX Python (inside Tokio runtime for wasmer-wasix)
    let exit_code = run_wasix_python(&config, python_args, args.verbose)?;

    std::process::exit(exit_code);
}
