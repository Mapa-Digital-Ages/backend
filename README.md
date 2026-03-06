1. Install:
    - Python 3.12.13:
        - Windows: winget install Python.Python.3.12
        - MacOS: brew install python@3.12
        - Linux (Ubuntu/Debian): sudo apt update && sudo apt install -y python3.12 python3.12-venv python3.12-dev

    - Docker:
        - Windows: winget install -e --id Docker.DockerDesktop
        - MacOS: brew install --cask docker-desktop
        - Linux (Ubuntu/Debian): sudo apt update && sudo apt install -y docker.io

    - Docker compose:
        - Windows: installed automatically with Docker Desktop
        - MacOS: installed automatically with Docker Desktop
        - Linux (Ubuntu/Debian): sudo apt install -y docker-compose-plugin

PS: If you use mac/linux and you don't have brew you should see a doctor...
In case you need to see a doctor, run this in the terminal:

/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

2. Create a file with the name '.env' with the content in '.env-example'. This will be our private variables.

3. Vscode Extensions:
    - Ruff
    - Rest Client

4. Run Application:
    After following steps 1 and 2, simply run on terminal: docker compose up --build

    To see if it is working, click in "Send Request" in requests/validate_request.rest ![example](github/image.png)
