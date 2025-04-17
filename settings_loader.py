import json, os

def load_settings(path='settings.json'):
    with open(path, 'r') as f:
        settings = json.load(f)
    
    # Expand paths
    for key in ['data_dir', 'logs_dir', 'project_root']:
        if key in settings:
            settings[key] = os.path.expanduser(settings[key])
    
    return settings

settings = load_settings()
