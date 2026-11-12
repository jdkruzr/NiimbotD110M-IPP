"""Internal status snapshot; reasons are our enums, not arbitrary IPP bits."""
import os
from pathlib import Path

# reason: 0 none, 1 cover, 2 paper, 3 RFID, 4 offline, 5 link,
#         6 recovery, 7 unknown, 8 cancelled.
def error_status(event):
    code = event.get('reasonId')
    message = str(event.get('message', 'Unknown printer error'))
    if type(code) is int and code == 1:
        return 1, 'Printer lid is open. Close it, then explicitly resubmit the job.'
    if type(code) is int and code == 20:
        return 3, 'Cannot read/write the roll RFID tag (error 20). Check the roll is installed and seated.'
    category = event.get('category')
    if category == 'offline':
        return 4, 'Cannot connect. Power on the printer and disconnect it in the phone app, then resubmit.'
    if category == 'link':
        return 5, 'Bluetooth connection lost. Output may be partial; inspect the printer before retrying.'
    return 7, message


def publish(folder, confirmed, reason, message):
    # Only supervisor-generated values enter the C reader. A rename publishes
    # the count and message together; newline sanitization keeps framing intact.
    message = ' '.join(str(message).split())[:450]
    temporary = Path(folder)/'status.tmp'
    temporary.write_text(f'1 {confirmed} {reason}\n{message}\n')
    os.replace(temporary, Path(folder)/'status.txt')
