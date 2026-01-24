"""
Congress Bill Tracker Bot for X (Twitter)
Automatically posts updates when bills in the 119th Congress make progress.

Requirements:
- Python 3.8+
- pip install requests tweepy python-dotenv anthropic

Setup:
1. Get a Congress.gov API key: https://api.congress.gov/sign-up/
2. Get X API credentials: https://developer.x.com/
3. Get an Anthropic API key: https://console.anthropic.com/
4. Create a .env file with your credentials (see .env.example)
"""

import os
import json
import time
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv
import tweepy
import anthropic

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bill_tracker.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuration
CONGRESS_API_KEY = os.getenv('CONGRESS_API_KEY')
CONGRESS_API_BASE = 'https://api.congress.gov/v3'
CONGRESS_NUMBER = 119  # Current Congress (2025-2026)

# X (Twitter) API credentials
X_API_KEY = os.getenv('X_API_KEY')
X_API_SECRET = os.getenv('X_API_SECRET')
X_ACCESS_TOKEN = os.getenv('X_ACCESS_TOKEN')
X_ACCESS_TOKEN_SECRET = os.getenv('X_ACCESS_TOKEN_SECRET')

# Anthropic API key
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')

# File to track which bills we've already posted about
POSTED_ACTIONS_FILE = 'posted_actions.json'

# File to store generated bill summaries
BILL_SUMMARIES_FILE = 'bill_summaries.json'

# File to track last known status of each bill
BILL_STATUS_FILE = 'bill_status.json'

# File to track scheduled markups we've posted about
SCHEDULED_MARKUPS_FILE = 'scheduled_markups.json'


def get_x_client() -> tweepy.Client:
    """Initialize and return the X API client."""
    return tweepy.Client(
        consumer_key=X_API_KEY,
        consumer_secret=X_API_SECRET,
        access_token=X_ACCESS_TOKEN,
        access_token_secret=X_ACCESS_TOKEN_SECRET
    )


def get_anthropic_client() -> anthropic.Anthropic:
    """Initialize and return the Anthropic client."""
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def load_posted_actions() -> dict:
    """Load the record of actions we've already posted about."""
    if Path(POSTED_ACTIONS_FILE).exists():
        with open(POSTED_ACTIONS_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_posted_actions(posted: dict) -> None:
    """Save the record of posted actions."""
    with open(POSTED_ACTIONS_FILE, 'w') as f:
        json.dump(posted, f, indent=2)


def load_bill_summaries() -> dict:
    """Load previously generated bill summaries."""
    if Path(BILL_SUMMARIES_FILE).exists():
        with open(BILL_SUMMARIES_FILE, 'r') as f:
            return json.load(f)
    return {}


def fetch_current_president() -> str:
    """
    Get the current US president's name.
    
    Returns:
        President's last name (e.g., "Trump")
    """
    # Hardcoded for reliability - update in January 2029
    return "Trump"


def save_bill_summaries(summaries: dict) -> None:
    """Save bill summaries."""
    with open(BILL_SUMMARIES_FILE, 'w') as f:
        json.dump(summaries, f, indent=2)


def load_bill_status() -> dict:
    """Load the last known status of each bill."""
    if Path(BILL_STATUS_FILE).exists():
        with open(BILL_STATUS_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_bill_status(status: dict) -> None:
    """Save the bill status records."""
    with open(BILL_STATUS_FILE, 'w') as f:
        json.dump(status, f, indent=2)


def load_scheduled_markups() -> dict:
    """Load the record of scheduled markups we've tracked."""
    if Path(SCHEDULED_MARKUPS_FILE).exists():
        with open(SCHEDULED_MARKUPS_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_scheduled_markups(markups: dict) -> None:
    """Save the scheduled markups tracking data."""
    with open(SCHEDULED_MARKUPS_FILE, 'w') as f:
        json.dump(markups, f, indent=2)


def fetch_recent_bills(days_back: int = 1) -> list:
    """
    Fetch bills that have had recent updates.
    
    Args:
        days_back: How many days back to look for activity
        
    Returns:
        List of bills with recent updates (includes latestAction)
    """
    from_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%dT00:00:00Z')
    
    all_bills = []
    offset = 0
    limit = 250
    
    while True:
        url = f"{CONGRESS_API_BASE}/bill/{CONGRESS_NUMBER}"
        params = {
            'api_key': CONGRESS_API_KEY,
            'format': 'json',
            'offset': offset,
            'limit': limit,
            'fromDateTime': from_date,
            'sort': 'updateDate+desc'
        }
        
        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            bills = data.get('bills', [])
            if not bills:
                break
                
            all_bills.extend(bills)
            
            pagination = data.get('pagination', {})
            if offset + limit >= pagination.get('count', 0):
                break
                
            offset += limit
            time.sleep(0.5)
            
        except requests.RequestException as e:
            logger.error(f"Error fetching bills: {e}")
            break
    
    logger.info(f"Found {len(all_bills)} bills with recent updates")
    return all_bills


def fetch_bill_details(bill_type: str, bill_number: int) -> Optional[dict]:
    """
    Fetch detailed information about a specific bill.
    """
    url = f"{CONGRESS_API_BASE}/bill/{CONGRESS_NUMBER}/{bill_type}/{bill_number}"
    params = {
        'api_key': CONGRESS_API_KEY,
        'format': 'json'
    }
    
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json().get('bill', {})
    except requests.RequestException as e:
        logger.error(f"Error fetching bill details for {bill_type}{bill_number}: {e}")
        return None


def fetch_bill_committees(bill_type: str, bill_number: int) -> list:
    """
    Fetch committees for a bill from the dedicated committees endpoint.
    """
    url = f"{CONGRESS_API_BASE}/bill/{CONGRESS_NUMBER}/{bill_type}/{bill_number}/committees"
    params = {
        'api_key': CONGRESS_API_KEY,
        'format': 'json'
    }
    
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json().get('committees', [])
    except requests.RequestException as e:
        logger.error(f"Error fetching committees for {bill_type}{bill_number}: {e}")
        return []


def fetch_bill_short_title(bill_type: str, bill_number: int) -> Optional[str]:
    """
    Fetch the short title for a bill from Congress.gov.
    Returns the short title if available, otherwise None.
    """
    url = f"{CONGRESS_API_BASE}/bill/{CONGRESS_NUMBER}/{bill_type}/{bill_number}/titles"
    params = {
        'api_key': CONGRESS_API_KEY,
        'format': 'json'
    }
    
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        titles = response.json().get('titles', [])
        
        # Look for short title first
        for title in titles:
            title_type = title.get('titleType', '').lower()
            if 'short' in title_type:
                return title.get('title', '')
        
        # No short title found
        return None
    except requests.RequestException as e:
        logger.error(f"Error fetching titles for {bill_type}{bill_number}: {e}")
        return None


def fetch_bill_summaries_from_api(bill_type: str, bill_number: int) -> Optional[str]:
    """
    Fetch the official CRS summary for a bill from Congress.gov.
    """
    url = f"{CONGRESS_API_BASE}/bill/{CONGRESS_NUMBER}/{bill_type}/{bill_number}/summaries"
    params = {
        'api_key': CONGRESS_API_KEY,
        'format': 'json'
    }
    
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        summaries = response.json().get('summaries', [])
        if summaries:
            # Get the most recent summary
            return summaries[0].get('text', '')
        return None
    except requests.RequestException as e:
        logger.error(f"Error fetching summaries for {bill_type}{bill_number}: {e}")
        return None


def fetch_bill_actions(bill_type: str, bill_number: int) -> list:
    """
    Fetch the action history for a specific bill.
    """
    url = f"{CONGRESS_API_BASE}/bill/{CONGRESS_NUMBER}/{bill_type}/{bill_number}/actions"
    params = {
        'api_key': CONGRESS_API_KEY,
        'format': 'json',
        'limit': 50
    }
    
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json().get('actions', [])
    except requests.RequestException as e:
        logger.error(f"Error fetching actions for {bill_type}{bill_number}: {e}")
        return []


# ============================================================================
# COMMITTEE CALENDAR / MARKUP FUNCTIONS
# ============================================================================

def fetch_committee_meeting_list(chamber: str, limit: int = 100) -> list:
    """
    Fetch list of committee meetings from the API.
    
    Args:
        chamber: 'house' or 'senate'
        limit: Maximum number of meetings to fetch
    
    Returns:
        List of meeting items (basic info only - eventId, url, updateDate)
    """
    url = f"{CONGRESS_API_BASE}/committee-meeting/{CONGRESS_NUMBER}/{chamber}"
    params = {
        'api_key': CONGRESS_API_KEY,
        'format': 'json',
        'limit': limit
    }
    
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json().get('committeeMeetings', [])
    except requests.RequestException as e:
        logger.error(f"Error fetching {chamber} committee meetings: {e}")
        return []


def fetch_meeting_details(meeting_url: str) -> dict:
    """
    Fetch full details for a single committee meeting.
    
    The list endpoint only provides eventId, url, updateDate.
    We need to fetch individual details to get type, meetingStatus, title, date.
    """
    params = {
        'api_key': CONGRESS_API_KEY,
        'format': 'json'
    }
    
    try:
        response = requests.get(meeting_url, params=params, timeout=30)
        response.raise_for_status()
        return response.json().get('committeeMeeting', {})
    except requests.RequestException as e:
        logger.error(f"Error fetching meeting details: {e}")
        return {}


def is_markup_meeting(meeting: dict) -> bool:
    """
    Determine if a meeting is a markup (committee vote on bills).
    
    House: type == 'Markup'
    Senate: Must check if 'markup' is in title (all Senate meetings have type 'Meeting')
    """
    meeting_type = meeting.get('type', '')
    title = meeting.get('title', '').lower()
    
    if meeting_type == 'Markup':
        return True
    if 'markup' in title:
        return True
    return False


def parse_meeting_date(date_str: str) -> Optional[datetime]:
    """Parse meeting date string to datetime object."""
    if not date_str:
        return None
    try:
        # Format: "2026-01-27T10:00:00Z"
        return datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%SZ')
    except ValueError:
        try:
            # Try without time
            return datetime.strptime(date_str[:10], '%Y-%m-%d')
        except ValueError:
            return None


def fetch_upcoming_markups(days_ahead: int = 14) -> list:
    """
    Fetch all markups scheduled within the next X days.
    
    Args:
        days_ahead: How many days ahead to look
        
    Returns:
        List of markup meetings with full details
    """
    logger.info(f"Fetching upcoming markups (next {days_ahead} days)...")
    
    now = datetime.now()
    cutoff = now + timedelta(days=days_ahead)
    
    all_markups = []
    
    for chamber in ['house', 'senate']:
        # Fetch meeting list
        meetings_list = fetch_committee_meeting_list(chamber, limit=100)
        logger.info(f"  {chamber.capitalize()}: {len(meetings_list)} meetings in list")
        
        # Fetch details for each meeting
        for meeting_item in meetings_list:
            meeting_url = meeting_item.get('url')
            if not meeting_url:
                continue
            
            details = fetch_meeting_details(meeting_url)
            if not details:
                continue
            
            # Check if it's a markup
            if not is_markup_meeting(details):
                continue
            
            # Check if it's within our date window
            meeting_date = parse_meeting_date(details.get('date', ''))
            if not meeting_date:
                continue
            
            # Only include future markups within window
            if meeting_date < now or meeting_date > cutoff:
                continue
            
            # Add chamber info and parsed date
            details['chamber'] = chamber.capitalize()
            details['parsed_date'] = meeting_date
            all_markups.append(details)
            
            # Small delay to be nice to API
            time.sleep(0.05)
    
    logger.info(f"Found {len(all_markups)} upcoming markups")
    return all_markups


def get_committee_name(meeting: dict) -> str:
    """Extract committee name from meeting details."""
    committees = meeting.get('committees', [])
    if committees:
        # Get the first committee's name
        return committees[0].get('name', 'Unknown Committee')
    return meeting.get('chamber', 'Unknown') + ' Committee'


def parse_bills_from_title(title: str) -> list:
    """
    Extract bill references from markup title.
    
    Example: "Markup: H.R. 2853, H.R. 6998..." → ["H.R. 2853", "H.R. 6998"]
    """
    if not title:
        return []
    
    # Pattern to match bill numbers: H.R. 123, S. 456, H.J.Res. 78, etc.
    pattern = r'(H\.R\.|S\.|H\.J\.Res\.|S\.J\.Res\.|H\.Con\.Res\.|S\.Con\.Res\.|H\.Res\.|S\.Res\.)\s*(\d+)'
    matches = re.findall(pattern, title)
    
    bills = []
    for match in matches:
        bill_type, bill_num = match
        bills.append(f"{bill_type} {bill_num}")
    
    return bills[:10]  # Limit to 10 bills to avoid huge lists


def create_markup_post(markup: dict, post_type: str, old_date: str = None) -> str:
    """
    Create tweet text for a markup event.
    
    Args:
        markup: Meeting details dict
        post_type: 'upcoming', 'update', or 'canceled'
        old_date: Previous date (for rescheduled posts)
    
    Returns:
        Tweet text
    """
    committee = get_committee_name(markup)
    title = markup.get('title', '')
    date_str = markup.get('date', '')
    status = markup.get('meetingStatus', 'Scheduled')
    chamber = markup.get('chamber', '')
    
    # Parse and format date
    meeting_date = parse_meeting_date(date_str)
    if meeting_date:
        formatted_date = meeting_date.strftime('%d-%m-%Y')
        formatted_time = meeting_date.strftime('%I:%M %p').lstrip('0')
    else:
        formatted_date = 'TBD'
        formatted_time = ''
    
    # Extract bills
    bills = parse_bills_from_title(title)
    bills_line = f"Bills: {', '.join(bills)}" if bills else ""
    
    # Build tweet based on type
    if post_type == 'upcoming':
        emoji = '📅'
        header = f"{emoji} MARKUP SCHEDULED | {committee}"
        date_line = f"Date: {formatted_date}" + (f" at {formatted_time}" if formatted_time else "")
        explanation = "Committee will vote on whether to advance these bills."
    
    elif post_type == 'update':
        if status == 'Postponed':
            emoji = '🔄'
            header = f"{emoji} MARKUP POSTPONED | {committee}"
            date_line = f"New date: TBD"
            if old_date:
                date_line += f"\n(Was: {old_date})"
            explanation = "Markup has been postponed to a later date."
        else:  # Rescheduled
            emoji = '🔄'
            header = f"{emoji} MARKUP RESCHEDULED | {committee}"
            date_line = f"New date: {formatted_date}" + (f" at {formatted_time}" if formatted_time else "")
            if old_date:
                date_line += f"\n(Was: {old_date})"
            explanation = "Committee vote has been moved to new date."
    
    elif post_type == 'canceled':
        emoji = '❌'
        header = f"{emoji} MARKUP CANCELED | {committee}"
        date_line = f"(Was scheduled for: {old_date})" if old_date else ""
        explanation = "Committee markup has been canceled."
    
    else:
        return ""
    
    # Build the tweet
    lines = [header]
    if date_line:
        lines.append(date_line)
    if bills_line:
        lines.append(bills_line)
    lines.append("")
    lines.append(explanation)
    
    return '\n'.join(lines)


def detect_markup_changes(current_markups: list, tracked_markups: dict) -> dict:
    """
    Compare current markup calendar to what we've tracked.
    
    Returns:
        {
            'new': [markups to post as UPCOMING],
            'rescheduled': [markups that changed date/status],
            'canceled': [markups that were canceled],
            'unchanged': [no action needed]
        }
    """
    changes = {
        'new': [],
        'rescheduled': [],
        'canceled': [],
        'unchanged': []
    }
    
    current_event_ids = set()
    
    for markup in current_markups:
        event_id = str(markup.get('eventId', ''))
        if not event_id:
            continue
        
        current_event_ids.add(event_id)
        status = markup.get('meetingStatus', 'Scheduled')
        date_str = markup.get('date', '')
        
        if event_id not in tracked_markups:
            # New markup we haven't seen
            if status == 'Scheduled':
                changes['new'].append(markup)
            elif status == 'Canceled':
                # New but already canceled - don't post
                pass
            else:
                # New but rescheduled/postponed - treat as new
                changes['new'].append(markup)
        else:
            # We've seen this markup before
            tracked = tracked_markups[event_id]
            old_status = tracked.get('status', 'Scheduled')
            old_date = tracked.get('date', '')
            
            if status == 'Canceled' and old_status != 'Canceled':
                # Was scheduled/rescheduled, now canceled
                markup['old_date'] = old_date
                changes['canceled'].append(markup)
            elif status in ('Rescheduled', 'Postponed') and old_status == 'Scheduled':
                # Status changed to rescheduled/postponed
                markup['old_date'] = old_date
                changes['rescheduled'].append(markup)
            elif status == 'Rescheduled' and date_str != old_date:
                # Date changed
                markup['old_date'] = old_date
                changes['rescheduled'].append(markup)
            else:
                changes['unchanged'].append(markup)
    
    # Check for markups that disappeared (might be canceled without status update)
    # Only flag if they were in our future window
    for event_id, tracked in tracked_markups.items():
        if event_id not in current_event_ids:
            tracked_date = parse_meeting_date(tracked.get('date', ''))
            if tracked_date and tracked_date > datetime.now():
                # Future markup disappeared - might be canceled
                # But we can't post about it without more info
                pass
    
    return changes


def extract_vote_from_action(action: dict) -> Optional[str]:
    """
    Extract vote count string from an action if available.
    """
    action_text = action.get('text', '')
    
    # Try to parse vote counts from action text
    vote_pattern = r'(\d{1,3})\s*[-–]\s*(\d{1,3})'
    match = re.search(vote_pattern, action_text)
    
    if match:
        yea = match.group(1)
        nay = match.group(2)
        return f"({yea}-{nay})"
    
    if 'voice vote' in action_text.lower():
        return "(voice vote)"
    
    if 'unanimous consent' in action_text.lower():
        return "(unanimous consent)"
    
    return None


def format_bill_type(bill_type: str) -> str:
    """Convert bill type code to readable format."""
    type_map = {
        'hr': 'H.R.',
        's': 'S.',
        'hjres': 'H.J.Res.',
        'sjres': 'S.J.Res.',
        'hconres': 'H.Con.Res.',
        'sconres': 'S.Con.Res.',
        'hres': 'H.Res.',
        'sres': 'S.Res.'
    }
    return type_map.get(bill_type.lower(), bill_type.upper())


def get_action_emoji(action_text: str) -> str:
    """Return an appropriate emoji based on the action type."""
    action_lower = action_text.lower()
    
    if 'passed' in action_lower and 'house' in action_lower:
        return '✅🏛️'
    elif 'passed' in action_lower and 'senate' in action_lower:
        return '✅🏛️'
    elif 'passed' in action_lower:
        return '✅🏛️'  # Generic passed
    elif 'signed by president' in action_lower or 'became public law' in action_lower:
        return '📜✍️'
    elif 'veto' in action_lower:
        return '❌'
    elif 'introduced' in action_lower:
        return '📋'
    elif 'referred to' in action_lower:
        return '📁'
    elif 'reported' in action_lower:
        return '📋'
    elif 'amendment' in action_lower:
        return '📝'
    elif 'cloture' in action_lower:
        return '⏱️'
    elif 'placed on' in action_lower and 'calendar' in action_lower:
        return '📅'
    elif 'vote' in action_lower or 'roll call' in action_lower:
        return '🗳️'
    else:
        return '📌'


def get_whats_next(action_text: str, action_history: list = None) -> str:
    """
    Return a plain-English explanation of what happens next after this action.
    
    Args:
        action_text: The current action text
        action_history: List of all actions for this bill (to check prior passages)
    """
    action_lower = action_text.lower()
    
    # Check action history for prior chamber passages
    passed_house = False
    passed_senate = False
    if action_history:
        for hist_action in action_history:
            hist_text = hist_action.get('text', '').lower()
            if 'passed' in hist_text and 'house' in hist_text:
                passed_house = True
            if 'passed' in hist_text and 'senate' in hist_text:
                passed_senate = True
    
    if 'signed by president' in action_lower:
        return "Policy implementation"
    elif 'vetoed' in action_lower or 'veto' in action_lower:
        return "Congress can override with 2/3 vote in both chambers or veto upheld"
    elif 'passed' in action_lower and 'house' in action_lower:
        # Check if Senate already passed
        if passed_senate:
            return "President's signature"
        else:
            return "Senate vote"
    elif 'passed' in action_lower and 'senate' in action_lower:
        # Check if House already passed
        if passed_house:
            return "President's signature"
        else:
            return "House vote"
    elif 'passed' in action_lower:
        return "Other chamber vote"
    elif 'conference report' in action_lower and ('agreed' in action_lower or 'adopted' in action_lower):
        return "President's signature"
    elif 'cloture' in action_lower and ('invoked' in action_lower or 'agreed' in action_lower):
        return "Senate floor vote"
    elif 'reported by' in action_lower:
        return "TBD (amendments, floor vote, tabled, stalls, or fails)"
    elif 'placed on' in action_lower and 'calendar' in action_lower:
        return "TBD (floor debate, floor vote, removed, or fails)"
    elif 'motion to proceed' in action_lower:
        return "TBD (debate begins, filibuster, or withdrawn)"
    elif 'discharged from' in action_lower:
        return "TBD (amendments, floor vote, tabled, stalls, or fails)"
    elif 'resolving differences' in action_lower:
        return "TBD (conference committee, chamber adopts amended text, stalls, or fails)"
    else:
        return "TBD"


def is_significant_action(action_text: str) -> bool:
    """
    Determine if an action is significant enough to post about.
    """
    significant_keywords = [
        'passed',
        'signed by president',
        'veto',
        'reported by',
        'placed on calendar',
        'cloture',
        'conference report',
        'resolving differences',
        'motion to proceed',
        'discharged from'
    ]
    
    action_lower = action_text.lower()
    return any(keyword in action_lower for keyword in significant_keywords)


def get_sponsor_info(bill: dict) -> str:
    """
    Extract sponsor information from bill details.
    
    Returns:
        Formatted sponsor string like "Rep. Mike Lawler (R-NY)"
    """
    sponsors = bill.get('sponsors', [])
    if not sponsors:
        return "Unknown"
    
    sponsor = sponsors[0]
    
    # Get name
    first_name = sponsor.get('firstName', '')
    last_name = sponsor.get('lastName', '')
    
    # Get title (Rep. or Sen.)
    # Try multiple fields since API format varies
    chamber = sponsor.get('chamber', '')
    
    # Also check bill type as fallback (H.R. = House, S. = Senate)
    bill_type = bill.get('type', '').lower()
    
    if chamber == 'House' or chamber == 'house':
        title = 'Rep.'
    elif chamber == 'Senate' or chamber == 'senate':
        title = 'Sen.'
    elif bill_type in ['hr', 'hres', 'hjres', 'hconres']:
        title = 'Rep.'
    elif bill_type in ['s', 'sres', 'sjres', 'sconres']:
        title = 'Sen.'
    else:
        title = ''
    
    # Get party and state
    party = sponsor.get('party', '')
    state = sponsor.get('state', '')
    
    # Format: Rep. Mike Lawler (R-NY)
    if title:
        name_part = f"{title} {first_name} {last_name}".strip()
    else:
        name_part = f"{first_name} {last_name}".strip()
    
    if party and state:
        return f"{name_part} ({party}-{state})"
    elif party:
        return f"{name_part} ({party})"
    else:
        return name_part


def get_committee_info(bill: dict) -> str:
    """
    Extract all committee information from bill details.
    Falls back to fetching from dedicated committees endpoint if needed.
    
    Returns:
        Formatted committee string like "House Financial Services, House Agriculture"
    """
    committees = bill.get('committees', {})
    
    # Try to get committee info from the bill details
    if isinstance(committees, dict):
        # Sometimes it's nested under 'item'
        committee_list = committees.get('item', [])
        if not committee_list:
            committee_list = committees.get('committees', [])
    elif isinstance(committees, list):
        committee_list = committees
    else:
        committee_list = []
    
    # If no committees in bill details, fetch from dedicated endpoint
    if not committee_list:
        bill_type = bill.get('type', '').lower()
        bill_number = bill.get('number', '')
        if bill_type and bill_number:
            committee_list = fetch_bill_committees(bill_type, bill_number)
    
    if not committee_list:
        return "None"
    
    # Extract all committee names (no limit)
    committee_names = []
    for comm in committee_list:
        if isinstance(comm, dict):
            name = comm.get('name', '')
            if name:
                # Shorten common prefixes
                name = name.replace('House Committee on ', 'House ')
                name = name.replace('Senate Committee on ', 'Senate ')
                name = name.replace('Committee on ', '')
                if name not in committee_names:  # Avoid duplicates
                    committee_names.append(name)
        elif isinstance(comm, str):
            if comm not in committee_names:
                committee_names.append(comm)
    
    if committee_names:
        return ', '.join(committee_names)
    
    return "None"


def generate_ai_summary(bill: dict, client: anthropic.Anthropic, is_signed: bool = False, short_title: str = None) -> str:
    """
    Generate a plain-English summary of the bill using Claude.
    
    Args:
        bill: Bill details dictionary
        client: Anthropic client
        is_signed: Whether the bill has been signed into law
        short_title: The short title to use in the summary (for consistency with header)
        
    Returns:
        AI-generated summary string
    """
    bill_type = format_bill_type(bill.get('type', ''))
    bill_number = bill.get('number', '')
    official_title = bill.get('title', 'No title available')
    
    # Use provided short title or fall back to official title
    display_title = short_title if short_title else official_title
    
    # Try to get official CRS summary
    crs_summary = fetch_bill_summaries_from_api(bill.get('type', '').lower(), bill_number)
    
    # Build prompt
    if crs_summary:
        source_text = f"Official title: {official_title}\n\nOfficial summary: {crs_summary}"
    else:
        source_text = f"Official title: {official_title}"
    
    if is_signed:
        # Bill is now law - use present tense
        prompt = f"""Summarize this law in 1-5 sentences based on its complexity. Use plain English, no jargon.

IMPORTANT RULES:
1. Start the summary with "The {display_title}" exactly as written
2. Do NOT repeat the bill name twice - start with "The {display_title}" only once, then continue with the verb
3. Use present tense (e.g., "creates", "establishes", "requires") since this is now law
4. For simple, focused laws: 1-2 sentences explaining what it does and who it affects
5. For complex omnibus laws: briefly list the main areas it addresses

{source_text}

Respond with ONLY the summary starting with "The {display_title}" followed immediately by a verb, no other preamble or labels."""
    else:
        # Bill not yet signed - use conditional language
        prompt = f"""Summarize this bill in 1-5 sentences based on its complexity. Use plain English, no jargon.

IMPORTANT RULES:
1. Start the summary with "The {display_title}" exactly as written
2. Do NOT repeat the bill name twice - start with "The {display_title}" only once, then continue with "would", "aims to", etc.
3. Use conditional language like "would", "aims to", "seeks to", or "proposes to" (vary the phrasing)
4. For simple, focused bills: 1-2 sentences explaining what it would do and who it would affect
5. For complex omnibus bills: briefly list the main areas it addresses

{source_text}

Respond with ONLY the summary starting with "The {display_title}" followed immediately by a verb, no other preamble or labels."""

    try:
        message = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=300,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        summary = message.content[0].text.strip()
        return summary
        
    except Exception as e:
        logger.error(f"Error generating AI summary: {e}")
        # Fallback to title
        return f"The {display_title[:150]}..." if len(display_title) > 150 else f"The {display_title}"


def get_or_generate_summary(bill: dict, bill_summaries: dict, client: anthropic.Anthropic, is_signed: bool = False, short_title: str = None) -> str:
    """
    Get existing summary or generate a new one.
    For signed bills, regenerate with present tense.
    """
    bill_type = bill.get('type', '').lower()
    bill_number = bill.get('number', '')
    
    # Use different cache key for signed vs unsigned
    if is_signed:
        bill_key = f"{bill_type}{bill_number}_signed"
    else:
        bill_key = f"{bill_type}{bill_number}"
    
    # Check if we already have a summary
    if bill_key in bill_summaries:
        return bill_summaries[bill_key]
    
    # Generate new summary
    summary = generate_ai_summary(bill, client, is_signed, short_title)
    
    # Save for future use
    bill_summaries[bill_key] = summary
    save_bill_summaries(bill_summaries)
    
    return summary


def create_action_label(action_text: str, vote_count: Optional[str] = None) -> str:
    """
    Create a concise label for the action, including vote count if available and appropriate.
    """
    action_lower = action_text.lower()
    
    # Track whether vote count is appropriate for this action type
    include_vote = False
    
    if 'passed house' in action_lower or ('passed' in action_lower and 'house' in action_lower):
        label = "Passed House"
        include_vote = True
    elif 'passed senate' in action_lower or ('passed' in action_lower and 'senate' in action_lower):
        label = "Passed Senate"
        include_vote = True
    elif 'on passage' in action_lower and 'passed' in action_lower:
        label = "Passed"
        include_vote = True
    elif 'passed' in action_lower:
        label = "Passed"
        include_vote = True
    elif 'signed by president' in action_lower:
        president = fetch_current_president()
        if president:
            label = f"Signed by President {president}"
        else:
            label = "Signed by President"
        # No vote for presidential signature
    elif 'became public law' in action_lower:
        label = "Became Public Law"
        # No vote, just procedural
    elif 'vetoed' in action_lower or 'veto' in action_lower:
        president = fetch_current_president()
        if president:
            label = f"Vetoed by President {president}"
        else:
            label = "Vetoed by President"
        # No vote for veto
    elif 'reported by' in action_lower:
        # Check for favorable/unfavorable
        if 'favorably' in action_lower:
            label = "Reported by Committee (Favorably)"
        elif 'unfavorably' in action_lower:
            label = "Reported by Committee (Unfavorably)"
        else:
            label = "Reported by Committee"
        # Committee votes not typically tracked
    elif 'ordered reported' in action_lower:
        label = "Ordered Reported"
        # Committee votes not typically tracked
    elif 'placed on' in action_lower and 'calendar' in action_lower:
        label = "Placed on Calendar"
        # No vote
    elif 'cloture' in action_lower:
        if 'invoked' in action_lower or 'agreed' in action_lower:
            label = "Cloture Invoked"
            include_vote = True  # Cloture requires a vote
        else:
            label = "Cloture Motion Filed"
            # Filing is not a vote
    elif 'conference report' in action_lower:
        if 'agreed' in action_lower or 'adopted' in action_lower:
            label = "Conference Report Agreed To"
            include_vote = True  # Agreement requires a vote
        else:
            label = "Conference Report Filed"
            # Filing is not a vote
    elif 'motion to proceed' in action_lower:
        label = "Motion to Proceed"
        include_vote = True  # May have a vote
    elif 'discharged from' in action_lower:
        label = "Discharged from Committee"
        # Procedural, no vote typically shown
    elif 'agreed to' in action_lower or 'adopted' in action_lower:
        label = "Agreed To"
        include_vote = True  # Usually involves a vote
    elif 'resolving differences' in action_lower:
        label = "Resolving Differences"
        # Procedural
    else:
        label = action_text[:40] + '...' if len(action_text) > 40 else action_text
        include_vote = True  # Default to showing if available
    
    if vote_count and include_vote:
        # Keep parentheses for cleaner format: "Passed House (279-141)"
        if not vote_count.startswith('('):
            vote_count = f"({vote_count})"
        label = f"{label} {vote_count}"
    
    return label


def create_tweet_text(bill: dict, action: dict, bill_summaries: dict, anthropic_client: anthropic.Anthropic) -> str:
    """
    Create the tweet text for a bill action.
    
    Format:
    H.R. 471 | Fix Our Forests Act | Rep. Bruce Westerman (R-AR) | House Agriculture
    
    22-01-2026 | ✅🏛️ Passed House, 279-141
    What's next: Senate vote
    
    Summary: The Fix Our Forests Act would streamline...
    [AI-Generated]
    
    https://congress.gov/bill/119th-congress/hr/471
    """
    bill_type_raw = bill.get('type', '').lower()
    bill_type = format_bill_type(bill.get('type', ''))
    bill_number = bill.get('number', '')
    bill_id = f"{bill_type} {bill_number}"
    
    # Get bill title - prefer short title over official title
    official_title = bill.get('title', 'Untitled Bill')
    short_title = fetch_bill_short_title(bill_type_raw, bill_number)
    bill_title = short_title if short_title else official_title
    
    # Get action info
    action_text = action.get('text', 'Action taken')
    action_date = action.get('actionDate', '')
    emoji = get_action_emoji(action_text)
    vote_count = extract_vote_from_action(action)
    action_label = create_action_label(action_text, vote_count)
    
    # Check if this is a signed into law action
    is_signed = 'signed by president' in action_text.lower()
    
    # Format the date (DD-MM-YYYY)
    formatted_date = ""
    if action_date:
        try:
            from datetime import datetime
            date_obj = datetime.strptime(action_date, '%Y-%m-%d')
            formatted_date = date_obj.strftime('%d-%m-%Y')
        except:
            formatted_date = action_date
    
    # Fetch action history to determine what's next accurately
    action_history = fetch_bill_actions(bill_type_raw, bill_number)
    
    # Get what's next explanation (with action history for accurate chamber tracking)
    whats_next = get_whats_next(action_text, action_history)
    
    # Get sponsor info
    sponsor = get_sponsor_info(bill)
    
    # Get committee info (all involved committees)
    committee = get_committee_info(bill)
    
    # Get or generate AI summary (pass short title so it matches header)
    summary = get_or_generate_summary(bill, bill_summaries, anthropic_client, is_signed, bill_title)
    
    # Congress.gov URL
    bill_type_url = bill.get('type', '').lower()
    url = f"https://congress.gov/bill/119th-congress/{bill_type_url}/{bill_number}"
    
    # Build the tweet
    # Line 1: Bill ID | Title | Sponsor | Committee(s) (omit committee if None)
    if committee and committee != "None":
        line1 = f"{bill_id} | {bill_title} | {sponsor} | {committee}"
    else:
        line1 = f"{bill_id} | {bill_title} | {sponsor}"
    
    # Line 2: Date | Emoji Action
    if formatted_date:
        line2 = f"{formatted_date} | {emoji} {action_label}"
    else:
        line2 = f"{emoji} {action_label}"
    
    # Line 3: What's next
    line3 = f"What's next: {whats_next}"
    
    # Summary section
    summary_line = f"Summary: {summary}\n[AI-Generated]"
    
    # URL
    url_line = url
    
    # Assemble tweet (X Premium allows up to 25,000 characters)
    tweet = f"{line1}\n\n{line2}\n{line3}\n\n{summary_line}\n\n{url_line}"
    
    return tweet


def post_to_x(client: tweepy.Client, tweet_text: str) -> bool:
    """Post a tweet to X."""
    try:
        response = client.create_tweet(text=tweet_text)
        logger.info(f"Posted tweet: {response.data['id']}")
        return True
    except tweepy.TweepyException as e:
        logger.error(f"Error posting tweet: {e}")
        return False


def generate_action_id(bill_type: str, bill_number: int, action: dict) -> str:
    """Generate a unique ID for a bill action to track what we've posted."""
    action_date = action.get('actionDate', '')
    action_text = action.get('text', '')[:50]
    return f"{bill_type}{bill_number}_{action_date}_{hash(action_text)}"


def get_action_priority(action_text: str) -> int:
    """
    Return priority level for an action (lower = more important).
    This ensures important actions are posted first when there's a cap.
    """
    action_lower = action_text.lower()
    
    # Priority 1: Most important - law enacted or vetoed
    if 'signed by president' in action_lower:
        return 1
    if 'veto' in action_lower:
        return 1
    
    # Priority 2: Major milestones - passed a chamber
    if 'passed' in action_lower:
        return 2
    
    # Priority 3: Near final - conference report
    if 'conference report' in action_lower:
        return 3
    
    # Priority 4: Significant progress
    if 'cloture' in action_lower:
        return 4
    if 'reported by' in action_lower:
        return 4
    
    # Priority 5: Everything else
    return 5


def run_tracker(post_to_twitter: bool = True, max_posts: int = 10) -> None:
    """
    Main function to run the bill tracker.
    
    Approach:
    1. Fetch all bills with recent updates
    2. Compare each bill's latestAction to what we stored
    3. If latestAction changed AND is significant → candidate for posting
    4. Sort by priority, post top ones (max 5 action posts)
    5. Check committee calendar for markup updates
    6. Post markup updates (max 5 markup posts)
    7. Update stored status
    """
    logger.info("Starting Congress Bill Tracker")
    
    # Split posts: 5 actions + 5 markups (or whatever max_posts allows)
    max_action_posts = max_posts // 2
    max_markup_posts = max_posts - max_action_posts
    
    # Initialize clients
    if post_to_twitter:
        try:
            x_client = get_x_client()
        except Exception as e:
            logger.error(f"Failed to initialize X client: {e}")
            return
    else:
        x_client = None
    
    try:
        anthropic_client = get_anthropic_client()
    except Exception as e:
        logger.error(f"Failed to initialize Anthropic client: {e}")
        return
    
    # Load data
    posted_actions = load_posted_actions()
    bill_summaries = load_bill_summaries()
    bill_status = load_bill_status()
    scheduled_markups = load_scheduled_markups()
    
    total_posts_made = 0
    
    # ========================================================================
    # PART 1: BILL ACTION POSTS (max 5)
    # ========================================================================
    logger.info("="*60)
    logger.info("PART 1: Checking bill actions...")
    logger.info("="*60)
    
    # Fetch recent bills (basic info with latestAction)
    bills = fetch_recent_bills(days_back=1)
    
    # Find bills with changed significant actions
    logger.info("Checking for status changes...")
    candidates = []
    seen_bill_ids = set()  # Prevent duplicates within this run
    
    for bill in bills:
        bill_type = bill.get('type', '').lower()
        bill_number = bill.get('number')
        
        if not bill_type or not bill_number:
            continue
        
        bill_key = f"{bill_type}{bill_number}"
        
        # Prevent duplicates in same run
        if bill_key in seen_bill_ids:
            continue
        seen_bill_ids.add(bill_key)
        
        # Get current latestAction
        latest_action = bill.get('latestAction')
        if not latest_action:
            continue
        
        action_date = latest_action.get('actionDate', '')
        action_text = latest_action.get('text', '')
        
        if not action_text:
            continue
        
        # Check if this is a significant action
        if not is_significant_action(action_text):
            # Update status but don't post
            bill_status[bill_key] = {
                'actionDate': action_date,
                'actionText': action_text
            }
            continue
        
        # Check if status changed from what we stored
        stored = bill_status.get(bill_key, {})
        stored_date = stored.get('actionDate', '')
        stored_text = stored.get('actionText', '')
        
        if action_date == stored_date and action_text == stored_text:
            # No change, skip
            continue
        
        # Status changed! This is a candidate
        priority = get_action_priority(action_text)
        candidates.append({
            'bill': bill,
            'bill_key': bill_key,
            'action_date': action_date,
            'action_text': action_text,
            'priority': priority
        })
    
    logger.info(f"Found {len(candidates)} bills with new significant actions")
    
    # Sort by priority (lower = more important)
    candidates.sort(key=lambda x: x['priority'])
    
    # Post top action candidates
    action_posts_made = 0
    
    if candidates:
        logger.info("Fetching details and posting bill actions...")
        
        for candidate in candidates:
            if action_posts_made >= max_action_posts:
                logger.info(f"Reached max action posts limit ({max_action_posts})")
                break
            
            bill = candidate['bill']
            bill_key = candidate['bill_key']
            bill_type = bill.get('type', '').lower()
            bill_number = bill.get('number')
            
            # Create action dict from latestAction for create_tweet_text
            action = {
                'actionDate': candidate['action_date'],
                'text': candidate['action_text']
            }
            
            # Generate action_id for dedup
            action_id = generate_action_id(bill_type, bill_number, action)
            
            # Skip if already posted
            if action_id in posted_actions:
                # But still update status
                bill_status[bill_key] = {
                    'actionDate': candidate['action_date'],
                    'actionText': candidate['action_text']
                }
                continue
            
            # Fetch full bill details
            bill_details = fetch_bill_details(bill_type, bill_number)
            if not bill_details:
                logger.warning(f"Could not fetch details for {bill_key}, skipping")
                continue
            
            # Create and post the tweet
            tweet_text = create_tweet_text(bill_details, action, bill_summaries, anthropic_client)
            logger.info(f"Posting action (priority {candidate['priority']}): {tweet_text[:80]}...")
            
            if post_to_twitter:
                if post_to_x(x_client, tweet_text):
                    posted_actions[action_id] = {
                        'posted_at': datetime.now().isoformat(),
                        'tweet': tweet_text
                    }
                    action_posts_made += 1
                    time.sleep(2)
            else:
                print(f"\n{'='*60}\nWOULD POST (ACTION):\n{tweet_text}\n{'='*60}")
                posted_actions[action_id] = {
                    'posted_at': datetime.now().isoformat(),
                    'tweet': tweet_text,
                    'test_mode': True
                }
                action_posts_made += 1
            
            # Update status after posting
            bill_status[bill_key] = {
                'actionDate': candidate['action_date'],
                'actionText': candidate['action_text']
            }
    else:
        logger.info("No new significant bill actions to post")
    
    total_posts_made += action_posts_made
    
    # ========================================================================
    # PART 2: MARKUP CALENDAR POSTS (max 5)
    # ========================================================================
    logger.info("="*60)
    logger.info("PART 2: Checking committee markup calendar...")
    logger.info("="*60)
    
    # Fetch upcoming markups (next 14 days)
    current_markups = fetch_upcoming_markups(days_ahead=14)
    
    # Detect changes
    changes = detect_markup_changes(current_markups, scheduled_markups)
    
    logger.info(f"Markup changes: {len(changes['new'])} new, "
                f"{len(changes['rescheduled'])} rescheduled, "
                f"{len(changes['canceled'])} canceled")
    
    markup_posts_made = 0
    
    # Process new markups
    for markup in changes['new']:
        if markup_posts_made >= max_markup_posts:
            logger.info(f"Reached max markup posts limit ({max_markup_posts})")
            break
        
        event_id = str(markup.get('eventId', ''))
        if not event_id:
            continue
        
        tweet_text = create_markup_post(markup, 'upcoming')
        if not tweet_text:
            continue
        
        logger.info(f"Posting new markup: {tweet_text[:80]}...")
        
        if post_to_twitter:
            if post_to_x(x_client, tweet_text):
                markup_posts_made += 1
                time.sleep(2)
        else:
            print(f"\n{'='*60}\nWOULD POST (MARKUP):\n{tweet_text}\n{'='*60}")
            markup_posts_made += 1
        
        # Track this markup
        meeting_date = parse_meeting_date(markup.get('date', ''))
        scheduled_markups[event_id] = {
            'eventId': event_id,
            'status': markup.get('meetingStatus', 'Scheduled'),
            'date': markup.get('date', ''),
            'formatted_date': meeting_date.strftime('%d-%m-%Y') if meeting_date else '',
            'committee': get_committee_name(markup),
            'title': markup.get('title', '')[:200],
            'first_posted': datetime.now().isoformat(),
            'last_post_type': 'upcoming'
        }
    
    # Process rescheduled/postponed markups
    for markup in changes['rescheduled']:
        if markup_posts_made >= max_markup_posts:
            break
        
        event_id = str(markup.get('eventId', ''))
        if not event_id:
            continue
        
        old_date = markup.get('old_date', '')
        if old_date:
            old_parsed = parse_meeting_date(old_date)
            old_date_formatted = old_parsed.strftime('%d-%m-%Y') if old_parsed else old_date
        else:
            old_date_formatted = scheduled_markups.get(event_id, {}).get('formatted_date', '')
        
        tweet_text = create_markup_post(markup, 'update', old_date_formatted)
        if not tweet_text:
            continue
        
        logger.info(f"Posting markup update: {tweet_text[:80]}...")
        
        if post_to_twitter:
            if post_to_x(x_client, tweet_text):
                markup_posts_made += 1
                time.sleep(2)
        else:
            print(f"\n{'='*60}\nWOULD POST (MARKUP UPDATE):\n{tweet_text}\n{'='*60}")
            markup_posts_made += 1
        
        # Update tracking
        meeting_date = parse_meeting_date(markup.get('date', ''))
        scheduled_markups[event_id]['status'] = markup.get('meetingStatus', 'Rescheduled')
        scheduled_markups[event_id]['date'] = markup.get('date', '')
        scheduled_markups[event_id]['formatted_date'] = meeting_date.strftime('%d-%m-%Y') if meeting_date else ''
        scheduled_markups[event_id]['last_post_type'] = 'update'
        scheduled_markups[event_id]['last_updated'] = datetime.now().isoformat()
    
    # Process canceled markups
    for markup in changes['canceled']:
        if markup_posts_made >= max_markup_posts:
            break
        
        event_id = str(markup.get('eventId', ''))
        if not event_id:
            continue
        
        old_date_formatted = markup.get('old_date', '')
        if not old_date_formatted:
            old_date_formatted = scheduled_markups.get(event_id, {}).get('formatted_date', '')
        
        tweet_text = create_markup_post(markup, 'canceled', old_date_formatted)
        if not tweet_text:
            continue
        
        logger.info(f"Posting markup canceled: {tweet_text[:80]}...")
        
        if post_to_twitter:
            if post_to_x(x_client, tweet_text):
                markup_posts_made += 1
                time.sleep(2)
        else:
            print(f"\n{'='*60}\nWOULD POST (MARKUP CANCELED):\n{tweet_text}\n{'='*60}")
            markup_posts_made += 1
        
        # Update tracking
        scheduled_markups[event_id]['status'] = 'Canceled'
        scheduled_markups[event_id]['last_post_type'] = 'canceled'
        scheduled_markups[event_id]['last_updated'] = datetime.now().isoformat()
    
    total_posts_made += markup_posts_made
    
    # ========================================================================
    # SAVE ALL DATA
    # ========================================================================
    save_posted_actions(posted_actions)
    save_bill_status(bill_status)
    save_scheduled_markups(scheduled_markups)
    
    logger.info("="*60)
    logger.info(f"Finished. Made {total_posts_made} total posts "
                f"({action_posts_made} actions, {markup_posts_made} markups)")
    logger.info("="*60)


def test_api_connections() -> None:
    """Test all API connections."""
    print("Testing Congress.gov API connection...")
    
    if not CONGRESS_API_KEY:
        print("❌ CONGRESS_API_KEY not set in environment")
    else:
        url = f"{CONGRESS_API_BASE}/bill/{CONGRESS_NUMBER}"
        params = {'api_key': CONGRESS_API_KEY, 'format': 'json', 'limit': 1}
        
        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            print(f"✅ Congress.gov API connection successful")
            print(f"   Found {data.get('pagination', {}).get('count', 0)} total bills in 119th Congress")
        except requests.RequestException as e:
            print(f"❌ Congress.gov API error: {e}")
    
    print("\nTesting X API connection...")
    
    if not all([X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET]):
        print("❌ X API credentials not fully set in environment")
    else:
        try:
            client = get_x_client()
            me = client.get_me()
            print(f"✅ X API connection successful")
            print(f"   Authenticated as: @{me.data.username}")
        except tweepy.TweepyException as e:
            print(f"❌ X API error: {e}")
    
    print("\nTesting Anthropic API connection...")
    
    if not ANTHROPIC_API_KEY:
        print("❌ ANTHROPIC_API_KEY not set in environment")
    else:
        try:
            client = get_anthropic_client()
            message = client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=50,
                messages=[{"role": "user", "content": "Say 'API working' in 2 words."}]
            )
            print(f"✅ Anthropic API connection successful")
        except Exception as e:
            print(f"❌ Anthropic API error: {e}")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Congress Bill Tracker Bot')
    parser.add_argument('--test', action='store_true', help='Run in test mode (no actual posts)')
    parser.add_argument('--check', action='store_true', help='Check API connections')
    parser.add_argument('--max-posts', type=int, default=10, help='Maximum posts per run')
    
    args = parser.parse_args()
    
    if args.check:
        test_api_connections()
    else:
        run_tracker(post_to_twitter=not args.test, max_posts=args.max_posts)
