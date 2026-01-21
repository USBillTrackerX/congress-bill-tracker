"""
Congress Bill Tracker Bot for X (Twitter)
Automatically posts updates when bills in the 119th Congress make progress.

Requirements:
- Python 3.8+
- pip install requests tweepy python-dotenv

Setup:
1. Get a Congress.gov API key: https://api.congress.gov/sign-up/
2. Get X API credentials: https://developer.x.com/
3. Create a .env file with your credentials (see .env.example)
"""

import os
import json
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv
import tweepy

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

# File to track which bills we've already posted about
POSTED_ACTIONS_FILE = 'posted_actions.json'


def get_x_client() -> tweepy.Client:
    """Initialize and return the X API client."""
    return tweepy.Client(
        consumer_key=X_API_KEY,
        consumer_secret=X_API_SECRET,
        access_token=X_ACCESS_TOKEN,
        access_token_secret=X_ACCESS_TOKEN_SECRET
    )


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


def fetch_recent_bills(days_back: int = 1) -> list:
    """
    Fetch bills that have had recent activity.
    
    Args:
        days_back: How many days back to look for activity
        
    Returns:
        List of bills with recent actions
    """
    # Calculate the date range
    from_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%dT00:00:00Z')
    
    bills_with_actions = []
    offset = 0
    limit = 250  # Max allowed by API
    
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
            
            # Check if there are more results
            pagination = data.get('pagination', {})
            if offset + limit >= pagination.get('count', 0):
                break
                
            offset += limit
            time.sleep(0.5)  # Rate limiting
            
        except requests.RequestException as e:
            logger.error(f"Error fetching bills: {e}")
            break
    
    logger.info(f"Found {len(bills_with_actions)} bills with recent activity")
    return bills_with_actions


def fetch_bill_details(bill_type: str, bill_number: int) -> Optional[dict]:
    """
    Fetch detailed information about a specific bill.
    
    Args:
        bill_type: Type of bill (hr, s, hjres, sjres, etc.)
        bill_number: The bill number
        
    Returns:
        Bill details dictionary or None
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


def fetch_bill_actions(bill_type: str, bill_number: int) -> list:
    """
    Fetch the action history for a specific bill.
    
    Args:
        bill_type: Type of bill
        bill_number: The bill number
        
    Returns:
        List of actions
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


def fetch_vote_details(roll_call_number: int, chamber: str, congress: int = CONGRESS_NUMBER) -> Optional[dict]:
    """
    Fetch vote details for a specific roll call vote.
    
    Args:
        roll_call_number: The roll call vote number
        chamber: 'house' or 'senate'
        congress: Congress number
        
    Returns:
        Vote details dictionary or None
    """
    url = f"{CONGRESS_API_BASE}/roll-call-vote/{congress}/{chamber}/{roll_call_number}"
    params = {
        'api_key': CONGRESS_API_KEY,
        'format': 'json'
    }
    
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json().get('rollCallVote', {})
    except requests.RequestException as e:
        logger.error(f"Error fetching vote details for {chamber} roll call {roll_call_number}: {e}")
        return None


def extract_vote_from_action(action: dict) -> Optional[str]:
    """
    Extract vote count string from an action if available.
    
    Args:
        action: Action dictionary
        
    Returns:
        Vote string like "(267-158)" or None
    """
    # Check if there's recorded vote info in the action
    recorded_votes = action.get('recordedVotes', [])
    
    if recorded_votes:
        for vote in recorded_votes:
            # Try to get vote totals from the recorded vote
            chamber = vote.get('chamber', '').lower()
            roll_num = vote.get('rollNumber')
            
            if roll_num:
                vote_details = fetch_vote_details(roll_num, chamber)
                if vote_details:
                    yea = vote_details.get('yea', {}).get('total', 0)
                    nay = vote_details.get('nay', {}).get('total', 0)
                    if yea or nay:
                        return f"({yea}-{nay})"
    
    # Try to parse vote counts from action text as fallback
    # Common patterns: "passed by Yea-Nay Vote. 267 - 158"
    #                  "Passed by the Yeas and Nays: 62 - 38"
    #                  "agreed to by voice vote"
    action_text = action.get('text', '')
    
    import re
    
    # Pattern for "X - Y" vote counts
    vote_pattern = r'(\d{1,3})\s*[-–]\s*(\d{1,3})'
    match = re.search(vote_pattern, action_text)
    
    if match:
        yea = match.group(1)
        nay = match.group(2)
        return f"({yea}-{nay})"
    
    # Check for voice vote
    if 'voice vote' in action_text.lower():
        return "(voice vote)"
    
    # Check for unanimous consent
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
    elif 'vote' in action_lower or 'roll call' in action_lower:
        return '🗳️'
    else:
        return '📌'


def is_significant_action(action_text: str) -> bool:
    """
    Determine if an action is significant enough to post about.
    
    This helps filter out routine procedural actions and focus on
    meaningful progress.
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


def create_tweet_text(bill: dict, action: dict) -> str:
    """
    Create the tweet text for a bill action.
    
    Args:
        bill: Bill information dictionary
        action: Action information dictionary
        
    Returns:
        Formatted tweet text (max 280 characters)
    """
    bill_type = format_bill_type(bill.get('type', ''))
    bill_number = bill.get('number', '')
    bill_id = f"{bill_type} {bill_number}"
    
    # Get bill title (truncate if needed)
    title = bill.get('title', 'No title available')
    
    # Get action info
    action_text = action.get('text', 'Action taken')
    action_date = action.get('actionDate', '')
    emoji = get_action_emoji(action_text)
    
    # Try to get vote count
    vote_count = extract_vote_from_action(action)
    
    # Create a short action summary instead of the full action text
    action_summary = create_action_summary(action_text, vote_count)
    
    # Congress.gov URL
    bill_type_url = bill.get('type', '').lower()
    url = f"https://congress.gov/bill/119th-congress/{bill_type_url}/{bill_number}"
    
    # Build the tweet
    # Format: emoji BILL_ID: Action Summary
    # Title (truncated)
    # Link
    
    # Calculate available space (280 - url length - newlines - emoji)
    url_length = 23  # X shortens all URLs to 23 characters
    base_length = len(emoji) + 2 + len(bill_id) + 2 + 2 + url_length  # emoji + spaces + bill_id + ": " + newlines + url
    
    available_for_content = 280 - base_length
    
    # Truncate action summary if needed
    max_action_length = min(len(action_summary), available_for_content - 50)  # Leave room for title
    if len(action_summary) > max_action_length:
        action_summary = action_summary[:max_action_length-3] + '...'
    
    # Calculate remaining space for title
    remaining = available_for_content - len(action_summary) - 1  # -1 for newline
    if len(title) > remaining:
        title = title[:remaining-3] + '...'
    
    tweet = f"{emoji} {bill_id}: {action_summary}\n{title}\n{url}"
    
    # Final safety check
    if len(tweet) > 280:
        # Truncate title more aggressively
        overage = len(tweet) - 280
        title = title[:-(overage + 3)] + '...'
        tweet = f"{emoji} {bill_id}: {action_summary}\n{title}\n{url}"
    
    return tweet


def create_action_summary(action_text: str, vote_count: Optional[str] = None) -> str:
    """
    Create a concise summary of the action, including vote count if available.
    
    Args:
        action_text: Full action text from the API
        vote_count: Optional vote count string like "(267-158)"
        
    Returns:
        Concise action summary
    """
    action_lower = action_text.lower()
    
    # Determine the action type and create a clean summary
    if 'passed house' in action_lower or ('passed' in action_lower and 'house' in action_lower):
        summary = "Passed House"
    elif 'passed senate' in action_lower or ('passed' in action_lower and 'senate' in action_lower):
        summary = "Passed Senate"
    elif 'signed by president' in action_lower:
        summary = "Signed by President"
    elif 'became public law' in action_lower:
        summary = "Became Public Law"
    elif 'vetoed' in action_lower or 'veto' in action_lower:
        summary = "Vetoed by President"
    elif 'reported by' in action_lower:
        # Try to extract committee name
        import re
        match = re.search(r'reported by[:\s]+(.+?)(?:\.|,|$)', action_text, re.IGNORECASE)
        if match:
            committee = match.group(1).strip()[:40]  # Limit length
            summary = f"Reported by {committee}"
        else:
            summary = "Reported by Committee"
    elif 'ordered reported' in action_lower:
        summary = "Ordered Reported by Committee"
    elif 'placed on' in action_lower and 'calendar' in action_lower:
        if 'senate' in action_lower:
            summary = "Placed on Senate Calendar"
        elif 'house' in action_lower:
            summary = "Placed on House Calendar"
        else:
            summary = "Placed on Calendar"
    elif 'cloture' in action_lower:
        if 'invoked' in action_lower or 'agreed' in action_lower:
            summary = "Cloture Invoked"
        else:
            summary = "Cloture Motion Filed"
    elif 'conference report' in action_lower:
        if 'agreed' in action_lower or 'adopted' in action_lower:
            summary = "Conference Report Agreed To"
        else:
            summary = "Conference Report Filed"
    elif 'agreed to' in action_lower or 'adopted' in action_lower:
        summary = "Agreed To"
    else:
        # Fall back to truncated original text
        summary = action_text[:60] + '...' if len(action_text) > 60 else action_text
    
    # Append vote count if available
    if vote_count:
        summary = f"{summary} {vote_count}"
    
    return summary


def post_to_x(client: tweepy.Client, tweet_text: str) -> bool:
    """
    Post a tweet to X.
    
    Args:
        client: Tweepy client
        tweet_text: Text to post
        
    Returns:
        True if successful, False otherwise
    """
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
    action_text = action.get('text', '')[:50]  # First 50 chars
    return f"{bill_type}{bill_number}_{action_date}_{hash(action_text)}"


def run_tracker(post_to_twitter: bool = True, max_posts: int = 10) -> None:
    """
    Main function to run the bill tracker.
    
    Args:
        post_to_twitter: Whether to actually post to X (False for testing)
        max_posts: Maximum number of posts to make in one run
    """
    logger.info("Starting Congress Bill Tracker")
    
    # Initialize X client
    if post_to_twitter:
        try:
            x_client = get_x_client()
        except Exception as e:
            logger.error(f"Failed to initialize X client: {e}")
            return
    else:
        x_client = None
    
    # Load previously posted actions
    posted_actions = load_posted_actions()
    
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
            
            # Check if this is a significant action
            action_text = action.get('text', '')
            if not is_significant_action(action_text):
                continue
            
            # Check if we've already posted about this action
            action_id = generate_action_id(bill_type, bill_number, action)
            if action_id in posted_actions:
                continue
            
            # Create and post the tweet
            tweet_text = create_tweet_text(bill_details, action)
            logger.info(f"New action found: {tweet_text[:100]}...")
            
            if post_to_twitter:
                if post_to_x(x_client, tweet_text):
                    posted_actions[action_id] = {
                        'posted_at': datetime.now().isoformat(),
                        'tweet': tweet_text
                    }
                    posts_made += 1
                    time.sleep(2)  # Rate limiting between posts
            else:
                # Testing mode - just log
                print(f"\n{'='*60}\nWOULD POST:\n{tweet_text}\n{'='*60}")
                posted_actions[action_id] = {
                    'posted_at': datetime.now().isoformat(),
                    'tweet': tweet_text,
                    'test_mode': True
                }
                posts_made += 1
        
        time.sleep(0.5)  # Rate limiting between bills
    
    # Save updated posted actions
    save_posted_actions(posted_actions)
    
    logger.info(f"Finished. Made {posts_made} posts.")


def test_api_connection() -> None:
    """Test the Congress.gov API connection."""
    print("Testing Congress.gov API connection...")
    
    if not CONGRESS_API_KEY:
        print("❌ CONGRESS_API_KEY not set in environment")
        return
    
    url = f"{CONGRESS_API_BASE}/bill/{CONGRESS_NUMBER}"
    params = {
        'api_key': CONGRESS_API_KEY,
        'format': 'json',
        'limit': 1
    }
    
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        print(f"✅ Congress.gov API connection successful")
        print(f"   Found {data.get('pagination', {}).get('count', 0)} total bills in 119th Congress")
    except requests.RequestException as e:
        print(f"❌ Congress.gov API error: {e}")


def test_x_connection() -> None:
    """Test the X API connection."""
    print("\nTesting X API connection...")
    
    if not all([X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET]):
        print("❌ X API credentials not fully set in environment")
        return
    
    try:
        client = get_x_client()
        # Get authenticated user info
        me = client.get_me()
        print(f"✅ X API connection successful")
        print(f"   Authenticated as: @{me.data.username}")
    except tweepy.TweepyException as e:
        print(f"❌ X API error: {e}")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Congress Bill Tracker Bot')
    parser.add_argument('--test', action='store_true', help='Run in test mode (no actual posts)')
    parser.add_argument('--check', action='store_true', help='Check API connections')
    parser.add_argument('--max-posts', type=int, default=10, help='Maximum posts per run')
    
    args = parser.parse_args()
    
    if args.check:
        test_api_connection()
        test_x_connection()
    else:
        run_tracker(post_to_twitter=not args.test, max_posts=args.max_posts)
