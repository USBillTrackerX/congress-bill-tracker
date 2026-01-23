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


def save_bill_summaries(summaries: dict) -> None:
    """Save bill summaries."""
    with open(BILL_SUMMARIES_FILE, 'w') as f:
        json.dump(summaries, f, indent=2)


def fetch_recent_bills(days_back: int = 1) -> list:
    """
    Fetch bills that have had recent activity.
    
    Args:
        days_back: How many days back to look for activity
        
    Returns:
        List of bills with recent actions
    """
    from_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%dT00:00:00Z')
    
    bills_with_actions = []
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
                
            bills_with_actions.extend(bills)
            
            pagination = data.get('pagination', {})
            if offset + limit >= pagination.get('count', 0):
                break
                
            offset += limit
            time.sleep(0.5)
            
        except requests.RequestException as e:
            logger.error(f"Error fetching bills: {e}")
            break
    
    logger.info(f"Found {len(bills_with_actions)} bills with recent activity")
    return bills_with_actions


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
    elif 'signed by president' in action_lower or 'became public law' in action_lower:
        return '📜✍️'
    elif 'veto' in action_lower:
        return '❌'
    elif 'introduced' in action_lower:
        return '📋'
    elif 'referred to' in action_lower:
        return '📁'
    elif 'reported' in action_lower:
        return '📊'
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


def get_procedural_explanation(action_text: str) -> str:
    """Return a plain-English explanation of what the procedural action means."""
    action_lower = action_text.lower()
    
    if 'became public law' in action_lower:
        return "Now officially law"
    elif 'signed by president' in action_lower:
        return "President has signed; becomes law"
    elif 'vetoed' in action_lower or 'veto' in action_lower:
        return "President rejected; Congress can override with 2/3 vote"
    elif 'passed' in action_lower and 'house' in action_lower:
        return "Approved by House; now goes to Senate"
    elif 'passed' in action_lower and 'senate' in action_lower:
        return "Approved by Senate; now goes to House or President"
    elif 'conference report' in action_lower and ('agreed' in action_lower or 'adopted' in action_lower):
        return "Both chambers approved final compromise version"
    elif 'cloture' in action_lower and ('invoked' in action_lower or 'agreed' in action_lower):
        return "Senate ended debate; final vote coming soon"
    elif 'reported by' in action_lower or 'ordered reported' in action_lower:
        return "Committee approved; eligible for floor vote"
    elif 'placed on' in action_lower and 'calendar' in action_lower:
        return "Scheduled for potential floor action"
    elif 'motion to proceed' in action_lower:
        return "Senate moving to begin debate"
    elif 'discharged from' in action_lower:
        return "Forced out of committee; rare procedural move"
    elif 'agreed to' in action_lower or 'adopted' in action_lower:
        return "Approved by the chamber"
    elif 'resolving differences' in action_lower:
        return "House and Senate working out different versions"
    else:
        return "Procedural action taken"


def is_significant_action(action_text: str) -> bool:
    """
    Determine if an action is significant enough to post about.
    """
    significant_keywords = [
        'passed',
        'agreed to',
        'adopted',
        'signed by president',
        'became public law',
        'veto',
        'reported by',
        'ordered reported',
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
    chamber = sponsor.get('chamber', '')
    if chamber == 'House':
        title = 'Rep.'
    elif chamber == 'Senate':
        title = 'Sen.'
    else:
        title = ''
    
    # Get party and state
    party = sponsor.get('party', '')
    state = sponsor.get('state', '')
    
    # Format: Rep. Mike Lawler (R-NY)
    name_part = f"{title} {first_name} {last_name}".strip()
    
    if party and state:
        return f"{name_part} ({party}-{state})"
    elif party:
        return f"{name_part} ({party})"
    else:
        return name_part


def get_committee_info(bill: dict) -> str:
    """
    Extract committee information from bill details.
    
    Returns:
        Formatted committee string like "House Financial Services; House Agriculture"
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
    
    if not committee_list:
        return "Not assigned"
    
    # Extract committee names
    committee_names = []
    for comm in committee_list[:3]:  # Limit to 3 committees
        if isinstance(comm, dict):
            name = comm.get('name', '')
            if name:
                # Shorten common prefixes
                name = name.replace('House Committee on ', 'House ')
                name = name.replace('Senate Committee on ', 'Senate ')
                name = name.replace('Committee on ', '')
                committee_names.append(name)
        elif isinstance(comm, str):
            committee_names.append(comm)
    
    if committee_names:
        return '; '.join(committee_names)
    
    return "Not assigned"


def generate_ai_summary(bill: dict, client: anthropic.Anthropic) -> str:
    """
    Generate a plain-English summary of the bill using Claude.
    
    Args:
        bill: Bill details dictionary
        client: Anthropic client
        
    Returns:
        AI-generated summary string
    """
    bill_type = format_bill_type(bill.get('type', ''))
    bill_number = bill.get('number', '')
    title = bill.get('title', 'No title available')
    
    # Try to get official CRS summary
    crs_summary = fetch_bill_summaries_from_api(bill.get('type', '').lower(), bill_number)
    
    # Build prompt
    if crs_summary:
        source_text = f"Official title: {title}\n\nOfficial summary: {crs_summary}"
    else:
        source_text = f"Official title: {title}"
    
    prompt = f"""Summarize this bill in 1-5 sentences based on its complexity. Use plain English, no jargon.

For simple, focused bills: 1-2 sentences explaining what it does and who it affects.
For complex omnibus bills covering many topics: briefly list the main areas it addresses.

{source_text}

Respond with ONLY the summary, no preamble or labels."""

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
        return title[:200] if len(title) > 200 else title


def get_or_generate_summary(bill: dict, bill_summaries: dict, client: anthropic.Anthropic) -> str:
    """
    Get existing summary or generate a new one.
    """
    bill_type = bill.get('type', '').lower()
    bill_number = bill.get('number', '')
    bill_key = f"{bill_type}{bill_number}"
    
    # Check if we already have a summary
    if bill_key in bill_summaries:
        return bill_summaries[bill_key]
    
    # Generate new summary
    summary = generate_ai_summary(bill, client)
    
    # Save for future use
    bill_summaries[bill_key] = summary
    save_bill_summaries(bill_summaries)
    
    return summary


def create_action_label(action_text: str, vote_count: Optional[str] = None) -> str:
    """
    Create a concise label for the action, including vote count if available.
    """
    action_lower = action_text.lower()
    
    if 'passed house' in action_lower or ('passed' in action_lower and 'house' in action_lower):
        label = "Passed House"
    elif 'passed senate' in action_lower or ('passed' in action_lower and 'senate' in action_lower):
        label = "Passed Senate"
    elif 'signed by president' in action_lower:
        label = "Signed by President"
    elif 'became public law' in action_lower:
        label = "Became Public Law"
    elif 'vetoed' in action_lower or 'veto' in action_lower:
        label = "Vetoed by President"
    elif 'reported by' in action_lower:
        label = "Reported by Committee"
    elif 'ordered reported' in action_lower:
        label = "Ordered Reported"
    elif 'placed on' in action_lower and 'calendar' in action_lower:
        label = "Placed on Calendar"
    elif 'cloture' in action_lower:
        if 'invoked' in action_lower or 'agreed' in action_lower:
            label = "Cloture Invoked"
        else:
            label = "Cloture Motion Filed"
    elif 'conference report' in action_lower:
        if 'agreed' in action_lower or 'adopted' in action_lower:
            label = "Conference Report Agreed To"
        else:
            label = "Conference Report Filed"
    elif 'motion to proceed' in action_lower:
        label = "Motion to Proceed"
    elif 'discharged from' in action_lower:
        label = "Discharged from Committee"
    elif 'agreed to' in action_lower or 'adopted' in action_lower:
        label = "Agreed To"
    elif 'resolving differences' in action_lower:
        label = "Resolving Differences"
    else:
        label = action_text[:40] + '...' if len(action_text) > 40 else action_text
    
    if vote_count:
        label = f"{label} {vote_count}"
    
    return label


def create_tweet_text(bill: dict, action: dict, bill_summaries: dict, anthropic_client: anthropic.Anthropic) -> str:
    """
    Create the tweet text for a bill action.
    
    Format:
    ✅🏛️ H.R. 1234: Passed House (267-158)
    Procedural Explanation: Approved by one chamber; now goes to Senate
    Bill Sponsor: Rep. Mike Lawler (R-NY)
    Committee: House Financial Services
    
    💡 Summary here. (AI-generated summary)
    
    https://congress.gov/bill/119th-congress/hr/1234
    """
    bill_type = format_bill_type(bill.get('type', ''))
    bill_number = bill.get('number', '')
    bill_id = f"{bill_type} {bill_number}"
    
    # Get action info
    action_text = action.get('text', 'Action taken')
    emoji = get_action_emoji(action_text)
    vote_count = extract_vote_from_action(action)
    action_label = create_action_label(action_text, vote_count)
    
    # Get procedural explanation
    procedural_explanation = get_procedural_explanation(action_text)
    
    # Get sponsor info
    sponsor = get_sponsor_info(bill)
    
    # Get committee info
    committee = get_committee_info(bill)
    
    # Get or generate AI summary
    summary = get_or_generate_summary(bill, bill_summaries, anthropic_client)
    
    # Congress.gov URL
    bill_type_url = bill.get('type', '').lower()
    url = f"https://congress.gov/bill/119th-congress/{bill_type_url}/{bill_number}"
    
    # Build the tweet
    # Line 1: Action
    line1 = f"{emoji} {bill_id}: {action_label}"
    
    # Line 2: Procedural explanation
    line2 = f"Procedural Explanation: {procedural_explanation}"
    
    # Line 3: Sponsor
    line3 = f"Bill Sponsor: {sponsor}"
    
    # Line 4: Committee
    line4 = f"Committee: {committee}"
    
    # Line 5: Summary with disclaimer
    summary_line = f"💡 {summary} (AI-generated summary)"
    
    # Line 6: URL
    line6 = url
    
    # Calculate available space (280 chars total, URL counts as 23)
    url_length = 23
    fixed_parts = f"{line1}\n{line2}\n{line3}\n{line4}\n\n\n{' ' * url_length}"
    available_for_summary = 280 - len(fixed_parts) - len("💡  (AI-generated summary)")
    
    # Truncate summary if needed
    if len(summary) > available_for_summary:
        summary = summary[:available_for_summary - 3] + '...'
        summary_line = f"💡 {summary} (AI-generated summary)"
    
    # Assemble tweet
    tweet = f"{line1}\n{line2}\n{line3}\n{line4}\n\n{summary_line}\n\n{line6}"
    
    # Final safety check - if still too long, truncate summary more
    while len(tweet) > 280:
        summary = summary[:-4] + '...'
        summary_line = f"💡 {summary} (AI-generated summary)"
        tweet = f"{line1}\n{line2}\n{line3}\n{line4}\n\n{summary_line}\n\n{line6}"
        
        if len(summary) < 20:
            # Give up on summary, just post without it
            tweet = f"{line1}\n{line2}\n{line3}\n{line4}\n\n{line6}"
            break
    
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


def run_tracker(post_to_twitter: bool = True, max_posts: int = 10) -> None:
    """
    Main function to run the bill tracker.
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
    
    # Fetch recent bills
    bills = fetch_recent_bills(days_back=1)
    
    posts_made = 0
    
    for bill in bills:
        if posts_made >= max_posts:
            logger.info(f"Reached max posts limit ({max_posts})")
            break
        
        bill_type = bill.get('type', '').lower()
        bill_number = bill.get('number')
        
        if not bill_type or not bill_number:
            continue
        
        # Get detailed bill info and actions
        bill_details = fetch_bill_details(bill_type, bill_number)
        if not bill_details:
            continue
        
        actions = fetch_bill_actions(bill_type, bill_number)
        
        for action in actions:
            if posts_made >= max_posts:
                break
            
            action_text = action.get('text', '')
            if not is_significant_action(action_text):
                continue
            
            action_id = generate_action_id(bill_type, bill_number, action)
            if action_id in posted_actions:
                continue
            
            # Create and post the tweet
            tweet_text = create_tweet_text(bill_details, action, bill_summaries, anthropic_client)
            logger.info(f"New action found: {tweet_text[:100]}...")
            
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
        
        time.sleep(0.5)
    
    # Save data
    save_posted_actions(posted_actions)
    
    logger.info(f"Finished. Made {posts_made} posts.")


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
