#!/usr/bin/env python3
"""
Reddit Keyword Monitor Bot
Monitors a real-time stream of new posts for keywords and sends email notifications.
This version is fully interactive, prompting for inputs if not provided via CLI.

Usage:
  - Interactive Mode (will ask for all inputs):
    python reddit_monitor.py

  - Command-Line Mode (overrides any interactive prompts):
    python reddit_monitor.py -s subreddit1 subreddit2 -k keyword1 -e notify@email.com
"""

import praw
import smtplib
import time
import json
import logging
import os
import argparse
from datetime import datetime
from typing import Set, List, Dict
from email.message import EmailMessage

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('reddit_monitor.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class RedditMonitor:
    def __init__(self, config_file: str = 'config.json', cli_args=None):
        """
        Initialize the Reddit monitor with configuration and CLI overrides.
        
        Args:
            config_file (str): Path to the configuration file.
            cli_args (argparse.Namespace): Parsed command-line arguments.
        """
        self.config = self.load_config(config_file)
        
        # Determine monitoring parameters, prioritizing CLI > Interactive > Config
        self.subreddits_to_monitor = cli_args.subreddits if cli_args.subreddits else self.config['monitoring']['subreddits']
        self.keywords_to_monitor = cli_args.keywords if cli_args.keywords else self.config['monitoring']['keywords']
        self.recipient_email = cli_args.email # This will be set from main()
        
        logger.info(f"Subreddits set to: {self.subreddits_to_monitor}")
        logger.info(f"Keywords set to: {self.keywords_to_monitor}")

        self.reddit = self.setup_reddit()
        
    def load_config(self, config_file: str) -> Dict:
        """Load configuration from JSON file"""
        try:
            with open(config_file, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.error(f"Config file '{config_file}' not found. Creating a template...")
            self.create_config_template(config_file)
            raise SystemExit("Please fill in the generated config.json file with your credentials.")
    
    def create_config_template(self, config_file: str):
        """Create a template configuration file"""
        template = {
            "reddit": {
                "client_id": "YOUR_REDDIT_CLIENT_ID",
                "client_secret": "YOUR_REDDIT_CLIENT_SECRET",
                "user_agent": "RedditMonitor/1.0 by YourUsername"
            },
            "email": {
                "smtp_server": "smtp.gmail.com",
                "smtp_port": 465,
                "sender_email": "your_email@gmail.com",
                "sender_password": "your_app_password",
                # This is now a fallback, as the script will ask for the email
                "notification_email": "recipient_email@example.com"
            },
            "monitoring": {
                # These are now fallbacks if not provided via CLI or interactive prompt
                "subreddits": ["python", "programming"],
                "keywords": ["api", "bot", "automation"],
                "case_sensitive": False
            }
        }
        
        with open(config_file, 'w') as f:
            json.dump(template, f, indent=4)
        
        logger.info(f"Created template config file: '{config_file}'")
    
    def setup_reddit(self) -> praw.Reddit:
        """Initialize and validate the Reddit API connection"""
        try:
            reddit_config = self.config['reddit']
            if "YOUR_REDDIT" in reddit_config["client_id"]:
                raise ValueError("Please replace placeholder Reddit credentials in config.json")

            reddit = praw.Reddit(
                client_id=reddit_config['client_id'],
                client_secret=reddit_config['client_secret'],
                user_agent=reddit_config['user_agent']
            )
            reddit.user.me()
            logger.info("Successfully connected to Reddit API (read-only mode)")
            return reddit
        except Exception as e:
            logger.error(f"Failed to connect to Reddit API: {e}")
            raise SystemExit("Could not establish a connection to Reddit. Please check your API credentials.")
    
    def send_email_notification(self, subject: str, body: str):
        """Sends an email notification."""
        if not self.recipient_email:
            logger.error("Email sending failed: No recipient email was provided.")
            logger.info("--- FALLBACK LOG ---")
            logger.info(f"Subject: {subject}\nBody:\n{body}")
            logger.info("--- END LOG ---")
            return

        email_config = self.config['email']
        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = email_config['sender_email']
        msg['To'] = self.recipient_email
        msg.set_content(body)
        
        try:
            logger.info(f"Attempting to send email to {self.recipient_email} via SSL...")
            with smtplib.SMTP_SSL(email_config['smtp_server'], email_config['smtp_port'], timeout=30) as server:
                server.login(email_config['sender_email'], email_config['sender_password'])
                server.send_message(msg)
            logger.info(f"Email notification sent successfully: '{subject}'")
        except Exception as e:
            logger.error(f"An unexpected error occurred while sending email: {e}", exc_info=True)

    def check_keywords(self, text: str) -> List[str]:
        """Check if the given text contains any of the monitored keywords."""
        case_sensitive = self.config['monitoring'].get('case_sensitive', False)
        found_keywords = set()
        search_text = text if case_sensitive else text.lower()
        
        for keyword in self.keywords_to_monitor:
            search_keyword = keyword if case_sensitive else keyword.lower()
            if search_keyword in search_text:
                found_keywords.add(keyword)
        
        return list(found_keywords)
    
    def handle_keyword_match(self, submission, keywords: List[str]):
        """Formats and sends a notification when a post matches keywords."""
        logger.info(f"Found keywords '{', '.join(keywords)}' in post: '{submission.title[:60]}...'")
        subject = f"Reddit Alert: Found '{', '.join(keywords)}' in r/{submission.subreddit.display_name}"
        post_url = f"https://reddit.com{submission.permalink}"
        body = f"""A new Reddit post matching your keywords was found.

Keywords: {', '.join(keywords)}
Subreddit: r/{submission.subreddit.display_name}
Post Title: {submission.title}
Author: u/{submission.author.name if submission.author else '[deleted]'}
Link: {post_url}

Post Content Preview:
{'-'*40}
{submission.selftext[:500]}{'...' if len(submission.selftext) > 500 else ''}
{'-'*40}

This is an automated message from the Reddit Monitor Bot.
"""
        self.send_email_notification(subject, body)
    
    def run(self):
        """Main monitoring loop using a real-time stream of new posts."""
        logger.info("Starting Reddit Monitor Bot in real-time stream mode...")
        logger.info(f"Notifications will be sent to: {self.recipient_email}")
        logger.info("Press Ctrl+C to stop the bot.")
        
        if not self.subreddits_to_monitor:
            logger.error("No subreddits to monitor. Exiting.")
            return

        subreddit_str = '+'.join(self.subreddits_to_monitor)
        subreddit = self.reddit.subreddit(subreddit_str)
        
        try:
            # Use subreddit.stream.submissions to get new posts in real-time
            # skip_existing=True ensures we don't process posts made before the script started
            for submission in subreddit.stream.submissions(skip_existing=True):
                logger.debug(f"New post in r/{submission.subreddit.display_name}: '{submission.title[:60]}...'")
                content_to_check = f"{submission.title} {submission.selftext or ''}"
                matched_keywords = self.check_keywords(content_to_check)
                
                if matched_keywords:
                    self.handle_keyword_match(submission, matched_keywords)
        except KeyboardInterrupt:
            logger.info("Bot stopped by user.")
        except Exception as e:
            logger.critical(f"An unexpected error occurred in the stream: {e}", exc_info=True)
            logger.info("The bot will exit. Please check the log and restart.")

def main():
    """Entry point for the script with command-line argument and interactive support."""
    parser = argparse.ArgumentParser(
        description="Monitors Reddit for keywords and sends email alerts.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument('-s', '--subreddits', nargs='+', metavar='SUB', help='One or more subreddits to monitor.')
    parser.add_argument('-k', '--keywords', nargs='+', metavar='WORD', help='One or more keywords to look for.')
    parser.add_argument('-e', '--email', metavar='EMAIL', help='The email address to send notifications to.')
    
    args = parser.parse_args()

    # --- Interactive Prompts ---
    # If a value was not provided via command-line flag, ask the user for it.
    if not args.subreddits:
        sub_input = input("▶ Enter subreddits to monitor (space-separated): ")
        args.subreddits = sub_input.split()

    if not args.keywords:
        key_input = input("▶ Enter keywords to look for (space-separated, use quotes in CLI for phrases): ")
        args.keywords = key_input.split()

    if not args.email:
        args.email = input("▶ Enter the recipient email address for notifications: ")

    try:
        monitor = RedditMonitor(cli_args=args)
        monitor.run()
    except SystemExit as e:
        logger.info(e)
    except Exception as e:
        logger.critical(f"A fatal error occurred: {e}", exc_info=True)

if __name__ == "__main__":
    main()

