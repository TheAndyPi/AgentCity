import { backend, frontend, npmArgs, python, root, run } from "./runtime.mjs";

try {
  run(process.execPath, npmArgs(["--prefix", frontend, "run", "typecheck"]));
  run(process.execPath, npmArgs(["--prefix", frontend, "test"]));
  run(python, ["-m", "pytest", "--junitxml=artifacts/test-results.xml"], {
    cwd: backend,
  });
  run(python, ["-m", "scripts.contracts", "--check"], { cwd: backend });
  run(python, ["-m", "ruff", "check", "app", "scripts", "tests"], {
    cwd: backend,
  });
  run(python, ["-m", "ruff", "format", "--check", "app", "scripts", "tests"], {
    cwd: backend,
  });
  console.log(`Verified both applications in ${root}`);
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
