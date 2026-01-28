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
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict

import requests
from dotenv import load_dotenv
import tweepy
import anthropic
from bs4 import BeautifulSoup

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


def get_whats_next(action_text: str, action_history: list = None, bill_type: str = None) -> str:
    """
    Return a plain-English explanation of what happens next after this action.
    
    Comprehensive coverage of all Congress.gov action patterns including:
    - Standard passage flow (both chambers + President for bills/joint resolutions)
    - Amendment ping-pong between chambers
    - Conference committee resolution
    - Vetoes (regular, pocket, override)
    - Procedural deaths (tabled, recommitted, indefinitely postponed)
    - Failed floor votes
    - Simple resolutions (single chamber)
    - Concurrent resolutions (both chambers, no President)
    
    Args:
        action_text: The current action text from Congress.gov
        action_history: List of all actions for this bill (to check prior passages)
        bill_type: Type of legislation (hr, s, hjres, sjres, hconres, sconres, hres, sres)
    """
    action_lower = action_text.lower()
    bill_type_lower = (bill_type or '').lower()
    
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
    
    # ============================================
    # UNIVERSAL PROCEDURAL DEATHS (check first - applies to all bill types)
    # These actions effectively kill legislation regardless of type
    # ============================================
    
    # "Motion to reconsider laid on the table" is GOOD - it locks in a previous vote
    # But "On motion to table the measure Agreed" KILLS the bill
    if 'motion to table' in action_lower and 'agreed' in action_lower:
        if 'motion to reconsider' not in action_lower:
            # This is tabling the actual bill/resolution, not the motion to reconsider
            if bill_type_lower in ['hres', 'sres', 'hconres', 'sconres']:
                return "Resolution Tabled"
            else:
                return "Bill Tabled"
    
    # Laid on table (without "motion to reconsider" context) - procedural death
    if 'laid on the table' in action_lower or 'laid on table' in action_lower:
        if 'motion to reconsider' not in action_lower:
            if bill_type_lower in ['hres', 'sres', 'hconres', 'sconres']:
                return "Resolution Tabled"
            else:
                return "Bill Tabled"
    
    # Indefinitely postponed - procedural death
    if 'indefinitely postponed' in action_lower:
        if bill_type_lower in ['hres', 'sres', 'hconres', 'sconres']:
            return "Resolution Indefinitely Postponed"
        else:
            return "Bill Indefinitely Postponed"
    
    # Motion to recommit agreed to (sends back to committee, usually kills bill)
    if 'motion to recommit' in action_lower and 'agreed' in action_lower:
        return "Recommitted to Committee"
    
    # ============================================
    # CHECK FOR AMENDMENTS (triggers ping-pong)
    # ============================================
    has_amendment = 'with an amendment' in action_lower or 'with amendments' in action_lower
    
    # Check if this is agreeing to the other chamber's amendment (resolves ping-pong)
    agrees_to_senate_amendment = 'agree' in action_lower and 'senate amendment' in action_lower
    agrees_to_house_amendment = 'agree' in action_lower and 'house amendment' in action_lower
    
    # ============================================
    # VETO-RELATED PATTERNS
    # ============================================
    # Check if override failed first (before checking if overridden)
    veto_override_failed = ('failed' in action_lower and 
                            ('override' in action_lower or 'notwithstanding' in action_lower))
    
    veto_overridden = (not veto_override_failed and
                       ('veto overridden' in action_lower or 
                        'notwithstanding' in action_lower or 
                        ('override' in action_lower and 'veto' in action_lower)))
    pocket_veto = 'pocket veto' in action_lower
    is_vetoed = (('vetoed' in action_lower or 
                  ('veto' in action_lower and 'message' not in action_lower and 'override' not in action_lower)) 
                 and not veto_overridden and not pocket_veto and not veto_override_failed)
    
    # ============================================
    # FAILED PASSAGE PATTERNS
    # ============================================
    # Be careful: "motion to recommit Failed" is GOOD for the bill
    # We want: "Failed of passage", "not agreed to", "rejected", "On passage Failed"
    failed_passage = False
    if 'failed' in action_lower:
        # Check it's actually the bill failing, not a motion against the bill failing
        if ('passage' in action_lower or 
            'suspend the rules' in action_lower or 
            'on the' in action_lower and 'resolution' in action_lower):
            failed_passage = True
        elif 'motion to recommit' not in action_lower and 'motion to table' not in action_lower:
            failed_passage = True
    if 'not agreed to' in action_lower and 'motion to recommit' not in action_lower:
        failed_passage = True
    if 'rejected' in action_lower and 'motion' not in action_lower:
        failed_passage = True
    
    # ============================================
    # SIMPLE RESOLUTIONS - Single chamber only
    # H.Res. = House only, S.Res. = Senate only
    # No amendment ping-pong, no other chamber, no President
    # ============================================
    if bill_type_lower == 'hres':
        if failed_passage:
            return "Resolution Failed"
        # Match: "Passed House", "agreed to...House", "agreeing to the resolution Agreed to"
        if ('passed' in action_lower or 'agreed to' in action_lower) and 'house' in action_lower:
            return "Policy Adoption"
        if 'agreeing to the resolution' in action_lower and 'agreed to' in action_lower:
            return "Policy Adoption"
        if 'passed' in action_lower:
            return "Policy Adoption"
    elif bill_type_lower == 'sres':
        if failed_passage:
            return "Resolution Failed"
        if ('passed' in action_lower or 'agreed to' in action_lower) and 'senate' in action_lower:
            return "Policy Adoption"
        if 'agreeing to the resolution' in action_lower and 'agreed to' in action_lower:
            return "Policy Adoption"
        if 'passed' in action_lower:
            return "Policy Adoption"
    
    # ============================================
    # CONCURRENT RESOLUTIONS - Both chambers, NO President
    # H.Con.Res. / S.Con.Res.
    # ============================================
    elif bill_type_lower in ['hconres', 'sconres']:
        if failed_passage:
            return "Resolution Failed"
        # Agreeing to other chamber's amendment = done
        if agrees_to_senate_amendment or agrees_to_house_amendment:
            return "Policy Adoption"
        # Conference report agreed = done
        if 'conference report' in action_lower and ('agreed' in action_lower or 'adopted' in action_lower):
            return "Policy Adoption"
        # Passed with amendment = goes back to other chamber
        if ('passed' in action_lower or 'agreed to' in action_lower) and 'house' in action_lower:
            if has_amendment and passed_senate:
                return "Senate Vote"
            elif passed_senate:
                return "Policy Adoption"
            else:
                return "Senate Vote"
        if ('passed' in action_lower or 'agreed to' in action_lower) and 'senate' in action_lower:
            if has_amendment and passed_house:
                return "House Vote"
            elif passed_house:
                return "Policy Adoption"
            else:
                return "House Vote"
        if 'passed' in action_lower:
            return "Other Chamber Vote"
    
    # ============================================
    # BILLS AND JOINT RESOLUTIONS - Both chambers + President
    # H.R. / S. / H.J.Res. / S.J.Res.
    # ============================================
    else:
        # === FINAL POSITIVE OUTCOMES ===
        if 'signed by president' in action_lower:
            return "Policy Adoption"
        if 'became public law' in action_lower:
            return "Policy Adoption"
        if veto_overridden:
            return "Policy Adoption"
        
        # === VETOES ===
        if pocket_veto:
            return "Pocket Veto - No Override Possible"
        if veto_override_failed:
            return "Veto Sustained"
        if is_vetoed:
            return "TBD (Congress may Attempt Override, 2/3 Vote Required)"
        
        # === FAILED PASSAGE ===
        if failed_passage:
            return "Bill Failed"
        
        # === RESOLVING DIFFERENCES ===
        # Agreeing to other chamber's amendment = Presidential Review (±10 Days)
        if agrees_to_senate_amendment or agrees_to_house_amendment:
            return "Presidential Review (±10 Days)"
        # Conference report agreed = Presidential Review (±10 Days)
        if 'conference report' in action_lower and ('agreed' in action_lower or 'adopted' in action_lower):
            return "Presidential Review (±10 Days)"
        
        # === PASSAGE WITH/WITHOUT AMENDMENTS ===
        # Passed House
        if ('passed' in action_lower or 'agreed to' in action_lower) and 'house' in action_lower:
            if has_amendment and passed_senate:
                # House amended a Senate bill, goes back to Senate
                return "Senate Vote"
            elif passed_senate:
                # Both passed clean
                return "Presidential Review (±10 Days)"
            else:
                return "Senate Vote"
        
        # Passed Senate
        if ('passed' in action_lower or 'agreed to' in action_lower) and 'senate' in action_lower:
            if has_amendment and passed_house:
                # Senate amended a House bill, goes back to House
                return "House Vote"
            elif passed_house:
                # Both passed clean
                return "Presidential Review (±10 Days)"
            else:
                return "House Vote"
        
        # Generic passed (shouldn't happen often)
        if 'passed' in action_lower:
            return "Other Chamber Vote"
    
    # ============================================
    # COMMON PROCEDURAL ACTIONS (applies to all types)
    # ============================================
    
    # Cloture failed - filibuster sustained (check BEFORE invoked)
    if 'cloture' in action_lower and ('not invoked' in action_lower or 
                                       ('failed' in action_lower and 'invoke' in action_lower)):
        return "Filibuster Sustained (60 Votes Not Reached)"
    
    # Cloture invoked - debate limited, floor vote coming
    if 'cloture' in action_lower and ('invoked' in action_lower or 'agreed' in action_lower):
        return "Senate Floor Vote"
    
    # Reported from committee
    if 'reported' in action_lower and ('committee' in action_lower or 'by the' in action_lower):
        return "TBD (Floor Scheduling, Amendments, Vote, or Stalls)"
    
    # Placed on calendar
    if 'placed on' in action_lower and 'calendar' in action_lower:
        return "TBD (Floor Debate, Amendments, Vote, or Stalls)"
    
    # Held at the desk (awaiting action in other chamber)
    if 'held at the desk' in action_lower or 'held at desk' in action_lower:
        return "TBD (Awaiting Floor Action)"
    
    # Received in other chamber
    if 'received in the senate' in action_lower:
        return "Senate Committee Or Floor Action"
    if 'received in the house' in action_lower:
        return "House Committee Or Floor Action"
    
    # Motion to proceed
    if 'motion to proceed' in action_lower:
        if 'agreed' in action_lower:
            return "Floor Debate Begins"
        elif 'failed' in action_lower or 'rejected' in action_lower:
            return "Motion to Proceed Failed"
        else:
            return "TBD (Debate Begins, Filibuster, or Withdrawn)"
    
    # Discharged from committee
    if 'discharged' in action_lower and 'committee' in action_lower:
        return "TBD (Floor Scheduling, Amendments, Vote, or Stalls)"
    
    # Resolving differences / amendments between chambers
    if 'resolving differences' in action_lower:
        return "TBD (Conference Committee Or Chamber Concurrence)"
    
    # Presented to President
    if 'presented to president' in action_lower:
        return "Awaiting President's Action"
    
    # Referred to committee
    if 'referred to' in action_lower and 'committee' in action_lower:
        return "TBD (Committee Hearing, Markup, Report, or Stalls)"
    
    # Committee hearing or markup
    if 'hearing' in action_lower or 'markup' in action_lower:
        return "TBD (Committee Vote, Report, or Stalls In Committee)"
    
    return "TBD"


def is_significant_action(action_text: str) -> bool:
    """
    Determine if an action is significant enough to post about.
    
    Includes:
    - Major progress (passed, reported, cloture, conference)
    - Final outcomes (signed, veto, became law)
    - Procedural deaths (tabled, indefinitely postponed, failed passage)
    
    Excludes high-frequency procedural actions like:
    - Referred to committee (happens to every bill)
    - Hearings/markups (too frequent)
    - Motion to recommit (sends to committee, not final)
    - Amendments proposed/agreed (too granular)
    """
    significant_keywords = [
        'passed',
        'signed by president',
        'veto',
        'reported by',
        'placed on calendar',
        'placed on senate legislative calendar',
        'placed on the union calendar',
        'placed on the house calendar',
        'cloture',
        'conference report',
        'resolving differences',
        'motion to proceed',
        'discharged from',
        # Procedural deaths - significant outcomes
        'laid on the table',
        'indefinitely postponed',
        'failed of passage',
        'failed to pass',
    ]
    
    action_lower = action_text.lower()
    
    # Check for basic keyword matches
    if any(keyword in action_lower for keyword in significant_keywords):
        # Exclude "motion to reconsider laid on the table" - that's just locking in a vote
        if 'laid on the table' in action_lower and 'motion to reconsider' in action_lower:
            return False
        return True
    
    # Special case: "On motion to table Agreed" (tabling the bill itself)
    if 'motion to table' in action_lower and 'agreed' in action_lower:
        if 'motion to reconsider' not in action_lower:
            return True
    
    return False


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
        if 'with an amendment' in action_lower or 'with amendments' in action_lower:
            label = "Passed House With Amendment"
        else:
            label = "Passed House"
        include_vote = True
    elif 'passed senate' in action_lower or ('passed' in action_lower and 'senate' in action_lower):
        if 'with an amendment' in action_lower or 'with amendments' in action_lower:
            label = "Passed Senate With Amendment"
        else:
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
            label = f"Signed by Pres. {president}"
        else:
            label = "Signed by Pres."
        # No vote for presidential signature
    elif 'became public law' in action_lower:
        label = "Became Public Law"
        # No vote, just procedural
    elif 'vetoed' in action_lower or 'veto' in action_lower:
        president = fetch_current_president()
        if president:
            label = f"Vetoed by Pres. {president}"
        else:
            label = "Vetoed by Pres."
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
    whats_next = get_whats_next(action_text, action_history, bill_type_raw)
    
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
    
    # Line 2: Calendar + Date | Emoji Action
    if formatted_date:
        line2 = f"📅 {formatted_date} | {emoji} {action_label}"
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
    4. Sort by priority, post top ones
    5. Update stored status
    """
    logger.info("Starting Congress Bill Tracker")
    
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
    
    posts_made = 0
    
    if not candidates:
        logger.info("No new significant actions to post")
    else:
        # Sort by priority (lower = more important)
        candidates.sort(key=lambda x: x['priority'])
        
        # Post top candidates
        logger.info("Fetching details and posting...")
        
        for candidate in candidates:
            if posts_made >= max_posts:
                logger.info(f"Reached max posts limit ({max_posts})")
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
            logger.info(f"Posting (priority {candidate['priority']}): {tweet_text[:100]}...")
            
            if post_to_twitter:
                if post_to_x(x_client, tweet_text):
                    posted_actions[action_id] = {
                        'posted_at': datetime.now().isoformat(),
                        'tweet': tweet_text
                    }
                    posts_made += 1
                    time.sleep(2)
            else:
                print(f"\n{'='*60}\nWOULD POST:\n{tweet_text}\n{'='*60}")
                posted_actions[action_id] = {
                    'posted_at': datetime.now().isoformat(),
                    'tweet': tweet_text,
                    'test_mode': True
                }
                posts_made += 1
            
            # Update status after posting
            bill_status[bill_key] = {
                'actionDate': candidate['action_date'],
                'actionText': candidate['action_text']
            }
    
    # Save all data
    save_posted_actions(posted_actions)
    save_bill_status(bill_status)
    
    logger.info(f"Part 1 complete. Made {posts_made} bill action posts.")
    
    # Part 2: Calendar/Markup posts
    markup_posts = run_calendar_tracker(x_client, post_to_twitter, max_posts=5)
    
    total_posts = posts_made + markup_posts
    logger.info("="*60)
    logger.info(f"Finished. Made {total_posts} total posts ({posts_made} actions, {markup_posts} markups)")
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


# =============================================================================
# CALENDAR FUNCTIONS - Fetch upcoming committee markups
# =============================================================================

def load_scheduled_markups() -> dict:
    """Load previously tracked scheduled markups."""
    if Path(SCHEDULED_MARKUPS_FILE).exists():
        with open(SCHEDULED_MARKUPS_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_scheduled_markups(markups: dict) -> None:
    """Save scheduled markups records."""
    with open(SCHEDULED_MARKUPS_FILE, 'w') as f:
        json.dump(markups, f, indent=2)


def fetch_senate_calendar() -> List[Dict]:
    """Fetch Senate committee meetings from official XML feed."""
    url = "https://www.senate.gov/general/committee_schedules/hearings.xml"
    meetings = []
    
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        root = ET.fromstring(response.text)
        
        for meeting in root.findall('meeting'):
            committee = meeting.find('committee')
            date_elem = meeting.find('date')
            matter = meeting.find('matter')
            room = meeting.find('room')
            
            if committee is None or date_elem is None:
                continue
            
            committee_name = committee.text.strip() if committee.text else ''
            date_str = date_elem.text.strip() if date_elem.text else ''
            matter_text = matter.text.strip() if matter is not None and matter.text else ''
            room_text = room.text.strip() if room is not None and room.text else ''
            
            meeting_date = None
            meeting_time = ''
            if date_str:
                try:
                    meeting_date = datetime.strptime(date_str, '%d-%b-%Y %I:%M %p')
                    meeting_time = meeting_date.strftime('%I:%M %p')
                except ValueError:
                    try:
                        meeting_date = datetime.strptime(date_str, '%d-%b-%Y')
                    except ValueError:
                        pass
            
            if not meeting_date:
                continue
            
            matter_lower = matter_text.lower()
            is_markup = (
                'business meeting' in matter_lower or
                'markup' in matter_lower or
                'to consider' in matter_lower or
                'executive session' in matter_lower
            )
            
            event_id = f"senate_{committee_name}_{meeting_date.strftime('%Y%m%d%H%M')}"
            event_id = re.sub(r'[^a-zA-Z0-9_]', '', event_id)
            
            meetings.append({
                'eventId': event_id,
                'chamber': 'Senate',
                'type': 'Markup' if is_markup else 'Hearing',
                'title': matter_text,
                'committee': committee_name,
                'date': meeting_date,
                'time': meeting_time,
                'formatted_date': meeting_date.strftime('%d-%m-%Y'),
                'room': room_text,
            })
    except Exception as e:
        logger.error(f"Error fetching Senate calendar: {e}")
    
    return meetings


def fetch_house_calendar() -> List[Dict]:
    """Fetch House committee meetings from docs.house.gov."""
    meetings = []
    today = datetime.now()
    
    for week_offset in range(3):
        week_start = today + timedelta(weeks=week_offset)
        monday = week_start - timedelta(days=week_start.weekday())
        sunday = monday + timedelta(days=6)
        
        date_range = f"{monday.strftime('%m%d%Y')}_{sunday.strftime('%m%d%Y')}"
        url = f"https://docs.house.gov/Committee/Calendar/ByWeek.aspx?WeekOf={date_range}"
        
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            for row in soup.find_all('tr', class_='meetingRow'):
                try:
                    comm_cell = row.find('td', class_='committee')
                    if not comm_cell:
                        continue
                    committee_name = comm_cell.get_text(strip=True)
                    
                    date_cell = row.find('td', class_='date')
                    time_cell = row.find('td', class_='time')
                    date_str = date_cell.get_text(strip=True) if date_cell else ''
                    time_str = time_cell.get_text(strip=True) if time_cell else ''
                    
                    meeting_date = None
                    if date_str:
                        for fmt in ['%m/%d/%Y', '%m-%d-%Y', '%B %d, %Y']:
                            try:
                                meeting_date = datetime.strptime(date_str, fmt)
                                break
                            except ValueError:
                                continue
                    
                    if not meeting_date:
                        continue
                    
                    title_cell = row.find('td', class_='meeting')
                    title = title_cell.get_text(strip=True) if title_cell else ''
                    
                    title_lower = title.lower()
                    is_markup = ('markup' in title_lower or 'business meeting' in title_lower or 'to consider' in title_lower)
                    
                    event_id = f"house_{committee_name}_{meeting_date.strftime('%Y%m%d')}"
                    event_id = re.sub(r'[^a-zA-Z0-9_]', '', event_id)
                    
                    meetings.append({
                        'eventId': event_id,
                        'chamber': 'House',
                        'type': 'Markup' if is_markup else 'Hearing',
                        'title': title,
                        'committee': committee_name,
                        'date': meeting_date,
                        'time': time_str,
                        'formatted_date': meeting_date.strftime('%d-%m-%Y'),
                        'room': '',
                    })
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"Error fetching House calendar: {e}")
    
    return meetings


def fetch_upcoming_events(days_ahead: int = 14) -> List[Dict]:
    """Fetch upcoming markups and confirmation hearings from both chambers."""
    logger.info("Fetching upcoming events from official sources...")
    
    senate_meetings = fetch_senate_calendar()
    logger.info(f"  Senate: {len(senate_meetings)} total meetings")
    
    house_meetings = fetch_house_calendar()
    logger.info(f"  House: {len(house_meetings)} total meetings")
    
    all_meetings = senate_meetings + house_meetings
    now = datetime.now()
    cutoff = now + timedelta(days=days_ahead)
    
    events = []
    for meeting in all_meetings:
        meeting_date = meeting.get('date')
        if not meeting_date or meeting_date < now or meeting_date > cutoff:
            continue
        
        meeting_type = meeting.get('type', '')
        title_lower = meeting.get('title', '').lower()
        
        # Filter out procedural business meetings
        is_procedural = (
            'pending calendar business' in title_lower or
            'pending business' in title_lower or
            'business meeting to consider pending' in title_lower
        )
        if is_procedural:
            continue
        
        # Include markups
        if meeting_type == 'Markup':
            events.append(meeting)
            continue
        
        # Include confirmation hearings
        is_confirmation = (
            'nomination' in title_lower or
            'confirmation' in title_lower or
            'to consider the nomination' in title_lower
        )
        if is_confirmation:
            meeting['type'] = 'Confirmation'
            events.append(meeting)
    
    markup_count = sum(1 for e in events if e.get('type') == 'Markup')
    confirm_count = sum(1 for e in events if e.get('type') == 'Confirmation')
    logger.info(f"  Found {len(events)} events ({markup_count} markups, {confirm_count} confirmations) in next {days_ahead} days")
    return events


def create_event_post(event: Dict) -> str:
    """Create tweet text for a markup or confirmation hearing."""
    committee = event.get('committee', 'Unknown Committee')
    title = event.get('title', '')
    formatted_date = event.get('formatted_date', 'TBD')
    meeting_time = event.get('time', '')
    event_type = event.get('type', 'Markup')
    chamber = event.get('chamber', 'Senate')
    
    date_time = f"{formatted_date} at {meeting_time}" if meeting_time else formatted_date
    
    # Get appropriate calendar link based on chamber
    if chamber == 'House':
        calendar_link = "https://docs.house.gov/Committee/Calendar/ByWeek.aspx"
    else:
        calendar_link = "https://www.senate.gov/committees"
    
    if event_type == 'Confirmation':
        # Confirmation hearing format
        lines = [f"📣 CONFIRMATION HEARING | {committee}"]
        lines.append(f"📅 {date_time}")
        lines.append("")
        
        if title:
            lines.append(f"Nominee: {title}")
        
        lines.append("")
        lines.append(calendar_link)
    else:
        # Markup format
        bills = []
        bill_pattern = r'(H\.?R\.?\s*\d+|S\.?\s*\d+|H\.?\s*Res\.?\s*\d+|S\.?\s*Res\.?\s*\d+)'
        for match in re.findall(bill_pattern, title, re.IGNORECASE):
            normalized = match.upper().replace(' ', '').replace('H.R.', 'H.R. ').replace('S.RES', 'S.Res. ').replace('H.RES', 'H.Res. ')
            if normalized not in bills:
                bills.append(normalized)
        
        lines = [f"📝 MARKUP SCHEDULED | {committee}"]
        lines.append(f"📅 {date_time}")
        lines.append("")
        
        if title:
            lines.append(f"Topic(s): {title}")
        
        if bills:
            lines.append(f"Bill(s): {', '.join(bills[:5])}")
        
        lines.append("")
        lines.append(calendar_link)
    
    return "\n".join(lines)


def run_calendar_tracker(x_client, post_to_twitter: bool = True, max_posts: int = 5) -> int:
    """
    Run the calendar tracker for markups and confirmation hearings.
    Returns number of posts made.
    """
    logger.info("="*60)
    logger.info("Checking committee calendar...")
    logger.info("="*60)
    
    scheduled_events = load_scheduled_markups()
    posts_made = 0
    
    upcoming_events = fetch_upcoming_events(days_ahead=14)
    
    new_events = []
    for event in upcoming_events:
        event_id = event.get('eventId', '')
        if event_id and event_id not in scheduled_events:
            new_events.append(event)
    
    logger.info(f"Found {len(upcoming_events)} upcoming events, {len(new_events)} are new")
    
    for event in new_events:
        if posts_made >= max_posts:
            break
        
        event_id = event.get('eventId', '')
        tweet_text = create_event_post(event)
        event_type = event.get('type', 'Markup')
        
        logger.info(f"Posting {event_type.lower()}: {tweet_text[:80]}...")
        
        if post_to_twitter:
            if post_to_x(x_client, tweet_text):
                scheduled_events[event_id] = {
                    'posted_at': datetime.now().isoformat(),
                    'type': event_type,
                    'committee': event.get('committee', ''),
                    'date': event.get('formatted_date', ''),
                    'title': event.get('title', '')[:200]
                }
                posts_made += 1
                time.sleep(2)
        else:
            print(f"\n{'='*60}\nWOULD POST ({event_type.upper()}):\n{tweet_text}\n{'='*60}")
            scheduled_events[event_id] = {
                'posted_at': datetime.now().isoformat(),
                'type': event_type,
                'committee': event.get('committee', ''),
                'date': event.get('formatted_date', ''),
                'title': event.get('title', '')[:200],
                'test_mode': True
            }
            posts_made += 1
    
    save_scheduled_markups(scheduled_events)
    return posts_made


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
