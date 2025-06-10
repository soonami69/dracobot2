import subprocess

scripts = ["setup.py", "import_and_randomize.py", "main.py"]

for script in scripts:
    print(f"Running {script}...")
    subprocess.run(["python", script], check=True)
