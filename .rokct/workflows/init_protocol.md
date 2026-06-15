# SOP: Initialize/Re-initialize Rokct Protocol (Local)

**Trigger**: You are returning to a project where `.rokct/` already exists, or you need to refresh the protocol configuration.

## Procedure

1.  **Run the Local Initiator**:
    *   **Windows/Unix/macOS**:
        ```bash
        python .rokct/initiate.py
        ```

2.  **Confirm Setup**:
    *   The script will update templates and ensure all required protocol files are present.

3.  **Done**:
    *   The protocol is now initialized/re-initialized. You can proceed to start a new session.

4.  **Session End**:
    *   Run `python .rokct/end_protocol.py` once your work in the project is completely done to clean up the protocol environment.
