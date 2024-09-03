from importlib import util
import os
import re
import sys
import subprocess


def extract_frontmatter(file_path):
    """
    Extract frontmatter as a dictionary from the specified file path.
    """
    frontmatter = {}
    frontmatter_started = False
    frontmatter_ended = False
    frontmatter_pattern = re.compile(r"^\s*([a-z_]+):\s*(.*)\s*$", re.IGNORECASE)

    try:
        with open(file_path, "r", encoding="utf-8") as file:
            first_line = file.readline()
            if first_line.strip() != '"""':
                # The file doesn't start with triple quotes
                return {}

            frontmatter_started = True

            for line in file:
                if '"""' in line:
                    if frontmatter_started:
                        frontmatter_ended = True
                        break

                if frontmatter_started and not frontmatter_ended:
                    match = frontmatter_pattern.match(line)
                    if match:
                        key, value = match.groups()
                        frontmatter[key.strip()] = value.strip()

    except FileNotFoundError:
        print(f"Error: The file {file_path} does not exist.")
        return {}
    except Exception as e:
        print(f"An error occurred: {e}")
        return {}

    return frontmatter


def install_frontmatter_requirements(requirements):
    if requirements:
        req_list = [req.strip() for req in requirements.split(",")]
        for req in req_list:
            print(f"Installing requirement: {req}")
            subprocess.check_call([sys.executable, "-m", "pip", "install", req])
    else:
        print("No requirements found in frontmatter.")
