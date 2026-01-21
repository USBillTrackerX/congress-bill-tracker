# Congress Bill Tracker Bot for X

An automated bot that tracks progress on bills in the 119th U.S. Congress and posts updates to X (Twitter).

## Features

- Monitors all bills in the 119th Congress (2025-2026)
- Posts updates for significant actions (passed votes, signed into law, vetoes, etc.)
- Filters out routine procedural actions to focus on meaningful progress
- Includes bill title, action description, and link to Congress.gov
- Tracks posted actions to avoid duplicates
- Configurable posting limits and test mode

## Example Posts

```
✅🏛️ H.R. 1234: Passed House
The Example Act of 2025 - A bill to improve...
https://congress.gov/bill/119th-congress/hr/1234

📜✍️ S. 567: Signed by President
The Important Policy Act - A bill establishing...
https://congress.gov/bill/119th-congress/s/567
```

## Prerequisites

- Python 3.8 or higher
- A Congress.gov API key (free)
- X Developer account with API access

## Setup Instructions

### Step 1: Get a Congress.gov API Key

1. Go to [https://api.congress.gov/sign-up/](https://api.congress.gov/sign-up/)
2. Fill out the form with your email
3. Check your email for the API key
4. This is completely free with no usage limits for reasonable use

### Step 2: Get X API Credentials

1. Go to [https://developer.x.com/](https://developer.x.com/)
2. Sign in with the X account you want the bot to post from
3. Apply for developer access if you haven't already
4. Create a new Project and App in the Developer Portal
5. In your App settings:
   - Go to "User authentication settings"
   - Select "Read and Write" permissions
   - Set App type to "Web App, Automated App or Bot"
   - Add a callback URL (can be `http://localhost`)
6. Go to "Keys and tokens":
   - Copy your API Key and API Secret
   - Generate Access Token and Secret (make sure it says "Read and Write")
   - Copy these as well

**API Costs:**
- Free tier: 1,500 posts/month (should be plenty for bill tracking)
- Basic tier ($200/month): 50,000 posts/month + read access
- New pay-per-use pilot: ~$0.01 per post

### Step 3: Install the Bot

```bash
# Clone or download the files
cd congress-bill-tracker

# Create a virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy the example env file and fill in your credentials
cp .env.example .env
# Edit .env with your actual API keys
```

### Step 4: Test the Setup

```bash
# Test that both APIs are working
python bill_tracker.py --check

# Run in test mode (shows what would be posted, but doesn't actually post)
python bill_tracker.py --test
```

### Step 5: Run the Bot

```bash
# Run once and post updates
python bill_tracker.py

# Limit the number of posts per run
python bill_tracker.py --max-posts 5
```

## Running Automatically

To run the bot automatically without manual intervention, you have several options:

### Option A: Cron Job (Linux/Mac)

Add to your crontab (`crontab -e`):

```bash
# Run every hour
0 * * * * cd /path/to/congress-bill-tracker && /path/to/venv/bin/python bill_tracker.py >> cron.log 2>&1

# Run every 6 hours
0 */6 * * * cd /path/to/congress-bill-tracker && /path/to/venv/bin/python bill_tracker.py >> cron.log 2>&1
```

### Option B: GitHub Actions (Free, Recommended)

Create `.github/workflows/bill-tracker.yml`:

```yaml
name: Congress Bill Tracker

on:
  schedule:
    # Run every 6 hours
    - cron: '0 */6 * * *'
  workflow_dispatch:  # Allow manual runs

jobs:
  track-bills:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: pip install -r requirements.txt
      
      - name: Run bill tracker
        env:
          CONGRESS_API_KEY: ${{ secrets.CONGRESS_API_KEY }}
          X_API_KEY: ${{ secrets.X_API_KEY }}
          X_API_SECRET: ${{ secrets.X_API_SECRET }}
          X_ACCESS_TOKEN: ${{ secrets.X_ACCESS_TOKEN }}
          X_ACCESS_TOKEN_SECRET: ${{ secrets.X_ACCESS_TOKEN_SECRET }}
        run: python bill_tracker.py --max-posts 10
      
      - name: Upload posted actions
        uses: actions/upload-artifact@v4
        with:
          name: posted-actions
          path: posted_actions.json
```

Then add your API keys as repository secrets in GitHub Settings > Secrets.

### Option C: Cloud Functions

You can deploy to:
- **AWS Lambda** with EventBridge for scheduling
- **Google Cloud Functions** with Cloud Scheduler
- **Vercel** with cron
- **Railway** or **Render** with background workers

### Option D: Always-On Server

If you have a VPS or always-on computer, use `systemd` timer or a process manager like `pm2`.

## Customization

### Filter What Gets Posted

Edit the `is_significant_action()` function in `bill_tracker.py` to change which actions trigger posts:

```python
significant_keywords = [
    'passed',
    'agreed to',
    'signed by president',
    # Add or remove keywords...
]
```

### Change the Tweet Format

Edit the `create_tweet_text()` function to customize how tweets look.

### Track Specific Bills Only

Modify `fetch_recent_bills()` to filter for specific:
- Bill types (HR, S, etc.)
- Committees
- Subjects/topics
- Sponsors

## Files

- `bill_tracker.py` - Main bot script
- `.env` - Your API credentials (don't commit this!)
- `.env.example` - Template for credentials
- `requirements.txt` - Python dependencies
- `posted_actions.json` - Tracks what's been posted (auto-created)
- `bill_tracker.log` - Log file (auto-created)

## Troubleshooting

**"403 Forbidden" from X API:**
- Make sure your Access Token has "Read and Write" permissions
- Regenerate your Access Token after changing permissions

**"Rate limit exceeded":**
- The bot includes rate limiting, but if you hit limits, wait an hour
- Consider reducing `--max-posts` or running less frequently

**"No bills found":**
- Congress might be in recess with no recent activity
- Try increasing `days_back` in `fetch_recent_bills()`

**Posts not appearing:**
- Check `bill_tracker.log` for errors
- Run with `--test` first to see what would be posted
- Verify credentials with `--check`

## License

MIT License - feel free to modify and use as you wish.

## Contributing

Pull requests welcome! Ideas for improvements:
- Add support for tracking specific topics/committees
- Include vote tallies in tweets
- Add thread support for related bills
- Create a web dashboard
