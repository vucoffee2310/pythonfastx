from fastapi import FastAPI
import os

app = FastAPI()

@app.get("/")
def read_root():
    # Get the current working directory
    cwd = os.getcwd()
    # List all files and directories in the current directory
    files = os.listdir(cwd)
    
    return {
        "message": "Hello from Vercel!",
        "current_directory": cwd,
        "root_folder_contents": files
    }
