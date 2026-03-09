import sys

def mock_analyzer_analyze(self, page, state, profile):
    pass

with open("auto_apply/agents/planner.py", "r") as f:
    text = f.read()

# Add a print statement before plan decisions to dump the nav_buttons
new_text = text.replace(
    'nav = state.metadata.get("nav_buttons", {})',
    '''nav = state.metadata.get("nav_buttons", {})
            import json
            print(f"\\n\\nDEBUG NAV: {json.dumps(nav, indent=2)}\\n\\n")'''
)
with open("auto_apply/agents/planner.py", "w") as f:
    f.write(new_text)

with open("auto_apply/html_cleaner.py", "r") as f:
    cleaner_text = f.read()

new_cleaner_text = cleaner_text.replace(
    'combined = f"{text} {value} {aria}"',
    '''combined = f"{text} {value} {aria}"
        print(f"DEBUG BTN found: {combined}")'''
)
with open("auto_apply/html_cleaner.py", "w") as f:
    f.write(new_cleaner_text)
