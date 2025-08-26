# Telegram CPM Recommendation Bot - Clean Version for GitHub
import sys
sys.stdout.reconfigure(encoding='utf-8')

import os
import asyncio
import json
import logging
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import threading
from statistics import mean

# External imports
import telebot
from telethon import TelegramClient, functions, types, errors
from telethon.errors import ChannelPrivateError, UsernameNotOccupiedError
import firebase_admin
from firebase_admin import credentials, firestore
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration
@dataclass
class Config:
    # Bot Configuration
    BOT_TOKEN: str = os.getenv('BOT_TOKEN', '')
    
    # Firebase Configuration
    FIREBASE_CREDENTIALS_PATH: str = os.getenv('FIREBASE_CREDENTIALS_PATH', './firebase-credentials.json')
    
    # API Keys
    TELEMETRIO_API_KEY: str = os.getenv('TELEMETRIO_API_KEY', '')
    TGSTAT_API_TOKEN: str = os.getenv('TGSTAT_API_TOKEN', '')
    
    # Harvester Configuration
    HARVESTER_API_ID: int = int(os.getenv('TG_API_ID', '0'))
    HARVESTER_API_HASH: str = os.getenv('TG_API_HASH', '')
    HARVESTER_DB_PATH: str = os.getenv('HARVESTER_DB_PATH', './stats.db')
    
    # Market Configuration
    MIN_CPM_TON: float = float(os.getenv('MIN_CPM_TON', '0.1'))
    TON_TO_USD: float = float(os.getenv('TON_TO_USD', '5.0'))
    MIN_SUBSCRIBERS: int = int(os.getenv('MIN_SUBSCRIBERS', '1000'))
    ACTIVITY_DAYS: int = int(os.getenv('ACTIVITY_DAYS', '14'))
    
    def validate(self) -> List[str]:
        """Validate configuration and return list of missing required fields"""
        missing = []
        
        if not self.BOT_TOKEN:
            missing.append('BOT_TOKEN')
        if not self.HARVESTER_API_ID or self.HARVESTER_API_ID == 0:
            missing.append('TG_API_ID')
        if not self.HARVESTER_API_HASH:
            missing.append('TG_API_HASH')
        
        return missing

class ChannelNiche(Enum):
    CRYPTO = "crypto"
    TECH = "tech"
    BUSINESS = "business"
    ENTERTAINMENT = "entertainment"
    NEWS = "news"
    GAMING = "gaming"
    FINANCE = "finance"
    EDUCATION = "education"
    LIFESTYLE = "lifestyle"

@dataclass
class ChannelMetrics:
    username: str
    title: str
    subscribers: int
    is_public: bool
    is_verified: bool
    description: str
    recent_posts: int
    avg_views: float
    engagement_rate: float
    last_post_date: datetime
    niche: ChannelNiche
    has_profile_photo: bool
    content_quality_score: float
    # Enhanced harvester metrics
    total_forwards: int = 0
    total_reactions: int = 0
    media_ratio: float = 0.0
    posts_per_day: float = 0.0

@dataclass
class EligibilityResult:
    eligible: bool
    reasons: List[str]
    warnings: List[str]
    confidence: float

@dataclass
class CPMRecommendation:
    conservative: float
    competitive: float
    aggressive: float
    reasoning: str
    market_position: str
    success_probability: float

# Firebase Database Manager
class FirebaseManager:
    def __init__(self, credentials_path: str):
        try:
            if os.path.exists(credentials_path):
                cred = credentials.Certificate(credentials_path)
                if not firebase_admin._apps:
                    firebase_admin.initialize_app(cred)
                self.db = firestore.client()
                logger.info("Firebase initialized successfully")
            else:
                logger.warning(f"Firebase credentials not found at {credentials_path}")
                self.db = None
        except Exception as e:
            logger.error(f"Firebase initialization failed: {e}")
            self.db = None

    async def save_channel_analysis(self, channel_data: Dict):
        if not self.db:
            return False
        try:
            doc_ref = self.db.collection('channel_analyses').document(channel_data['username'])
            doc_ref.set({
                **channel_data,
                'analyzed_at': datetime.now(),
                'analysis_count': firestore.Increment(1)
            }, merge=True)
            return True
        except Exception as e:
            logger.error(f"Failed to save channel analysis: {e}")
            return False

# Enhanced Harvester Integration Class with Bot API
class TelegramHarvester:
    """Integrates with harvester.py's SQLite cache + Bot API for comprehensive channel data"""
    REFRESH_CACHE = 6 * 3600  # 6 hours

    def __init__(self, api_id: int, api_hash: str, db_path: str, bot_token: str = ""):
        self.api_id = api_id
        self.api_hash = api_hash
        self.db_path = db_path
        self.bot_token = bot_token
        self.log = logging.getLogger(__name__)
        self.db = None

    def _get_db_connection(self):
        """Get a fresh database connection for this thread"""
        return sqlite3.connect(self.db_path)

    async def _get_bot_api_info(self, handle: str) -> Optional[Dict]:
        """Get basic channel info using Bot API (verification + description)"""
        if not self.bot_token:
            return None
        
        try:
            handle = handle.lstrip('@')
            url = f"https://api.telegram.org/bot{self.bot_token}/getChat"
            params = {"chat_id": f"@{handle}"}
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('ok'):
                    chat = data['result']
                    return {
                        'title': chat.get('title', ''),
                        'description': chat.get('description', ''),
                        'is_verified': chat.get('is_verified', False),
                        'username': chat.get('username', handle)
                    }
            else:
                self.log.warning(f"Bot API failed for @{handle}: {response.status_code}")
                
        except Exception as e:
            self.log.error(f"Bot API error for @{handle}: {e}")
        
        return None

    def load_from_cache(self, handle: str):
        try:
            handle = handle.lstrip('@')
            db = self._get_db_connection()
            
            # Use column names instead of position mapping
            row = db.execute('''SELECT handle, title, description, subs, avg_views, 
                                    posts_per_day, total_forwards, total_reactions, 
                                    media_ratio, is_verified, updated 
                                FROM channel_stats WHERE handle=?''', (handle,)).fetchone()
            db.close()
            
            if not row:
                return None
            
            data = {
                'handle': row[0],
                'title': row[1], 
                'description': row[2],
                'subs': row[3],
                'avg_views': row[4],
                'posts_per_day': row[5],
                'total_forwards': row[6],
                'total_reactions': row[7],
                'media_ratio': row[8],
                'is_verified': bool(row[9]),
                'updated': row[10]
            }
            data['username'] = data['handle']
            
            return data
        
        except Exception as e:
            self.log.error(f"Failed to load harvester cache for {handle}: {e}")
            return None

    async def get_stats(self, handle: str):
        """Get channel stats from harvester cache + Bot API for verification"""
        handle = handle.lstrip('@')
        
        # Step 1: Get analytics data from harvester cache
        cached = self.load_from_cache(handle)
        now = time.time()
        
        # Step 2: Get fresh harvester data if cache is stale
        harvester_data = None
        if not cached or now - cached.get('updated', 0) > self.REFRESH_CACHE:
            try:
                import sys
                import os
                
                # Add harvester directory to path
                harvester_dir = os.path.dirname(self.db_path)
                if harvester_dir not in sys.path:
                    sys.path.insert(0, harvester_dir)
                
                import importlib
                harvester = importlib.import_module('harvester')
                self.log.info(f"Fetching fresh harvester data for {handle}")
                harvester_data = await harvester.get_stats(handle)
            except Exception as e:
                self.log.error(f"Failed to fetch fresh harvester data for {handle}: {e}")
        
        # Use fresh data if available, otherwise cached
        analytics_data = harvester_data if harvester_data else cached
        
        if not analytics_data:
            self.log.warning(f"No harvester data available for @{handle}")
            return None

        # Step 3: Get real verification status and description from Bot API
        bot_api_data = await self._get_bot_api_info(handle)
        
        # Step 4: Merge data - Bot API overrides verification and description
        final_data = analytics_data.copy()
        
        if bot_api_data:
            self.log.info(f"Merging Bot API data for @{handle}")
            # Override with real Bot API data
            final_data['is_verified'] = bot_api_data['is_verified']
            final_data['description'] = bot_api_data['description']
            final_data['title'] = bot_api_data['title'] or final_data.get('title', handle)
            final_data['data_sources'] = 'harvester+bot_api'
        
        # Add freshness indicator
        final_data['fresh'] = harvester_data is not None
        
        return final_data

# TGStat API Integration
class TGStatAnalyzer:
    """TGStat.com API integration for comprehensive channel data"""
    
    def __init__(self, api_token: str = ""):
        self.api_token = api_token
        self.base_url = "https://api.tgstat.ru"
        self.headers = {
            'User-Agent': 'TelegramCPMBot/1.0',
            'Accept': 'application/json'
        }
        if api_token:
            self.headers['Authorization'] = f'Token {api_token}'
    
    async def get_channel_data(self, username: str) -> Optional[Dict]:
        """Get comprehensive channel data from TGStat"""
        username = username.lstrip('@')
        
        try:
            # Get channel info from TGStat
            info_response = requests.get(
                f"{self.base_url}/channels/get",
                params={'channelId': f'@{username}'},
                headers=self.headers,
                timeout=15
            )
            
            if info_response.status_code == 200:
                info_data = info_response.json()
                if info_data.get('ok'):
                    result = info_data.get('result', {})
                    logger.info(f"TGStat data retrieved for @{username}")
                    return result
                else:
                    logger.warning(f"TGStat API error: {info_data.get('description', 'Unknown error')}")
                    return None
            elif info_response.status_code == 404:
                logger.warning(f"Channel @{username} not found in TGStat")
                return None
            else:
                logger.warning(f"TGStat API returned status {info_response.status_code}")
                return None
            
        except Exception as e:
            logger.error(f"TGStat request failed for @{username}: {e}")
            return None
    
    def process_tgstat_data(self, username: str, data: Dict) -> Optional[ChannelMetrics]:
        """Convert TGStat data to ChannelMetrics format"""
        try:
            # Extract basic info
            title = data.get('title', username)
            description = data.get('description', '')
            subscribers = data.get('participantsCount', 0)
            
            # TGStat provides limited engagement data in free tier
            # We'll estimate from available data
            avg_views = 0
            engagement_rate = 0
            posts_per_day = 0
            
            # Try to get some metrics if available
            if 'avgPostReach' in data:
                avg_views = data['avgPostReach']
                engagement_rate = (avg_views / subscribers * 100) if subscribers > 0 else 0
            
            # Estimate activity level
            if 'postsCount' in data and 'createdAt' in data:
                try:
                    created_date = datetime.fromisoformat(data['createdAt'].replace('Z', '+00:00'))
                    days_active = (datetime.now().replace(tzinfo=created_date.tzinfo) - created_date).days
                    if days_active > 0:
                        posts_per_day = data['postsCount'] / days_active
                except:
                    posts_per_day = 0.5  # Default estimate
            
            # Set reasonable defaults for missing data
            last_post_date = datetime.now() - timedelta(days=1)
            if 'lastPostDate' in data:
                try:
                    last_post_date = datetime.fromisoformat(data['lastPostDate'].replace('Z', '+00:00'))
                    last_post_date = last_post_date.replace(tzinfo=None)
                except:
                    pass
            
            # Classify niche
            niche = self._classify_niche_tgstat(title, description)
            
            # Calculate content quality score
            content_quality = self._assess_tgstat_quality(data, subscribers, engagement_rate)
            
            return ChannelMetrics(
                username=username,
                title=title,
                subscribers=int(subscribers),
                is_public=True,  # TGStat only tracks public channels
                is_verified=data.get('verified', False),
                description=description,
                recent_posts=max(int(posts_per_day * 7), 1),  # Estimate weekly posts
                avg_views=float(avg_views),
                engagement_rate=round(engagement_rate, 2),
                last_post_date=last_post_date,
                niche=niche,
                has_profile_photo=True,  # Assume true for TGStat channels
                content_quality_score=content_quality,
                total_forwards=0,  # Not available in TGStat free tier
                total_reactions=0,  # Not available in TGStat free tier
                media_ratio=0.5,  # Default estimate
                posts_per_day=float(posts_per_day)
            )
            
        except Exception as e:
            logger.error(f"Error processing TGStat data for @{username}: {e}")
            return None
    
    def _classify_niche_tgstat(self, title: str, description: str) -> ChannelNiche:
        """Classify niche for TGStat data"""
        text = (title + ' ' + description).lower()
        
        # Enhanced keywords including Russian/Ukrainian terms
        keywords = {
            ChannelNiche.CRYPTO: ['crypto', 'bitcoin', 'blockchain', 'defi', 'nft', 'trading', 'btc', 'eth'],
            ChannelNiche.TECH: ['tech', 'technology', 'programming', 'ai', 'software'],
            ChannelNiche.BUSINESS: ['business', 'entrepreneur', 'startup', 'marketing'],
            ChannelNiche.FINANCE: ['finance', 'investment', 'stock', 'forex', 'money'],
            ChannelNiche.NEWS: ['news', 'breaking', 'daily', 'update'],
            ChannelNiche.GAMING: ['gaming', 'game', 'esports', 'gamer'],
            ChannelNiche.EDUCATION: ['education', 'learning', 'course', 'tutorial'],
            ChannelNiche.ENTERTAINMENT: ['entertainment', 'fun', 'meme', 'funny'],
        }
        
        for niche, niche_keywords in keywords.items():
            if any(keyword in text for keyword in niche_keywords):
                return niche
        
        return ChannelNiche.ENTERTAINMENT
    
    def _assess_tgstat_quality(self, data: Dict, subscribers: int, engagement_rate: float) -> float:
        """Assess content quality from TGStat data"""
        score = 0.5  # Base score
        
        # Engagement rate bonus
        if engagement_rate > 20:
            score += 0.3
        elif engagement_rate > 10:
            score += 0.2
        elif engagement_rate > 5:
            score += 0.1
        
        # Subscriber count indicates established channel
        if subscribers > 50000:
            score += 0.15
        elif subscribers > 10000:
            score += 0.1
        elif subscribers > 1000:
            score += 0.05
        
        # Description completeness
        if data.get('description') and len(data.get('description', '')) > 50:
            score += 0.1
        
        # Verification bonus
        if data.get('verified', False):
            score += 0.15
        
        # Channel age/maturity
        if 'createdAt' in data:
            try:
                created_date = datetime.fromisoformat(data['createdAt'].replace('Z', '+00:00'))
                age_days = (datetime.now().replace(tzinfo=created_date.tzinfo) - created_date).days
                if age_days > 365:  # Over 1 year old
                    score += 0.1
            except:
                pass
        
        return min(score, 1.0)

# Enhanced Channel Analyzer with Harvester Integration + TGStat
class ChannelAnalyzer:
    def __init__(self, config: Config):
        self.config = config
        
        # Initialize Telemetr.io
        self.telemetrio_headers = {
            'accept': 'application/json',
            'x-api-key': config.TELEMETRIO_API_KEY,
            'User-Agent': 'TelegramCPMBot/1.0'
        }
        self.telemetrio_base_url = "https://api.telemetr.io/v1"
        
        # Initialize TGStat
        self.tgstat = TGStatAnalyzer(config.TGSTAT_API_TOKEN)
        logger.info(f"TGStat initialized with token: {'Yes' if config.TGSTAT_API_TOKEN else 'No'}")
        
        # Initialize Harvester with Bot API integration
        self.harvester = None
        if config.HARVESTER_API_ID and config.HARVESTER_API_HASH:
            self.harvester = TelegramHarvester(
                config.HARVESTER_API_ID, 
                config.HARVESTER_API_HASH,
                config.HARVESTER_DB_PATH,
                config.BOT_TOKEN  # Pass bot token for Bot API integration
            )
            logger.info("Harvester initialized with Bot API integration")
        else:
            logger.warning("Harvester not initialized - missing TG_API_ID or TG_API_HASH")

    async def analyze_channel(self, username: str) -> Optional[ChannelMetrics]:
        """
        Enhanced multi-source channel analysis:
        1) Telemetr.io (premium analytics)
        2) Harvester (local cache + Bot API)  
        3) TGStat (comprehensive fallback)
        """
        username = username.lstrip('@')

        # Step 1: Try Telemetr.io first
        telemetrio_data = await self._get_telemetrio_data(username)
        if telemetrio_data:
            logger.info(f"Using Telemetr.io data for @{username}")
            metrics = self._process_telemetrio_data(username, telemetrio_data)

            # Merge with harvester data if needed
            if self.harvester:
                needs_desc = not metrics.description or not metrics.description.strip()
                needs_posts = metrics.posts_per_day == 0.0
                needs_inter = (metrics.total_reactions == 0 and
                               metrics.total_forwards == 0 and
                               metrics.media_ratio == 0.0)

                if needs_desc or needs_posts or needs_inter:
                    harv = await self.harvester.get_stats(username)
                    if harv:
                        if needs_desc and harv.get("description"):
                            metrics.description = harv["description"]
                        if needs_posts and harv.get("posts_per_day") is not None:
                            metrics.posts_per_day = harv["posts_per_day"]
                        if needs_inter:
                            metrics.total_reactions = harv.get("total_reactions", 0)
                            metrics.total_forwards = harv.get("total_forwards", 0)
                            metrics.media_ratio = harv.get("media_ratio", 0.0)
                        if harv.get("is_verified") is not None:
                            metrics.is_verified = harv["is_verified"]
            return metrics

        # Step 2: Try Harvester
        if self.harvester:
            logger.info(f"Trying harvester for @{username}")
            harvester_data = await self.harvester.get_stats(username)
            if harvester_data:
                logger.info(f"Using Harvester data for @{username}")
                return self._process_harvester_data(harvester_data)

        # Step 3: Try TGStat as final fallback
        logger.info(f"Trying TGStat for @{username}")
        tgstat_data = await self.tgstat.get_channel_data(username)
        if tgstat_data:
            logger.info(f"Using TGStat data for @{username}")
            return self.tgstat.process_tgstat_data(username, tgstat_data)

        # No data source worked
        logger.error(f"No data source available for @{username}")
        return None

    async def _get_telemetrio_data(self, username: str) -> Optional[Dict]:
        """Get channel data from Telemetr.io"""
        if not self.config.TELEMETRIO_API_KEY:
            return None
            
        try:
            endpoints = [
                f"{self.telemetrio_base_url}/channel/info",
                f"{self.telemetrio_base_url}/channel/stats"
            ]
            
            combined_data = {}
            
            for endpoint in endpoints:
                try:
                    response = requests.get(
                        endpoint,
                        headers=self.telemetrio_headers,
                        params={"handle": username},
                        timeout=10
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        combined_data.update(data)
                        logger.info(f"Telemetr.io {endpoint.split('/')[-1]} success for @{username}")
                    elif response.status_code == 404:
                        logger.warning(f"Channel @{username} not in Telemetr.io account")
                        continue
                    else:
                        logger.warning(f"Telemetr.io {endpoint.split('/')[-1]} returned {response.status_code}")
                        
                except requests.exceptions.RequestException as e:
                    logger.error(f"Telemetr.io request failed: {e}")
                    continue
            
            return combined_data if combined_data else None
            
        except Exception as e:
            logger.error(f"Telemetr.io integration error: {e}")
            return None

    def _process_telemetrio_data(self, username: str, data: Dict) -> ChannelMetrics:
        """Convert Telemetr.io data to ChannelMetrics"""
        title = data.get('title', data.get('name', username))
        subscribers = self._extract_subscribers(data)
        
        avg_views = data.get('avg_views', data.get('avgViews', 0))
        if isinstance(avg_views, str):
            avg_views = float(avg_views.replace(',', '').replace(' ', ''))
        
        engagement_rate = 0.0
        if subscribers > 0 and avg_views > 0:
            engagement_rate = (avg_views / subscribers) * 100
        
        is_verified = data.get('verified', data.get('is_verified', False))
        description = data.get('description', data.get('about', ''))
        recent_posts = data.get('posts_last_week', data.get('recent_posts', 0))
        last_post_date = self._parse_last_post_date(data)
        niche = self._classify_niche(title, description)
        content_quality = self._assess_telemetrio_quality(data)
        
        return ChannelMetrics(
            username=username,
            title=title,
            subscribers=int(subscribers),
            is_public=True,
            is_verified=is_verified,
            description=description,
            recent_posts=recent_posts,
            avg_views=float(avg_views),
            engagement_rate=round(engagement_rate, 2),
            last_post_date=last_post_date,
            niche=niche,
            has_profile_photo=data.get('has_photo', True),
            content_quality_score=content_quality,
            # Default harvester metrics
            total_forwards=0,
            total_reactions=0,
            media_ratio=0.0,
            posts_per_day=0.0
        )

    def _process_harvester_data(self, data: Dict) -> ChannelMetrics:
        """Convert Harvester data to ChannelMetrics with real Bot API verification"""
        engagement_rate = 0.0
        if data.get('subs', 0) and data.get('avg_views', 0):
            engagement_rate = (data['avg_views'] / data['subs']) * 100

        title = (
            data.get('title')
            or data.get('username')
            or data.get('handle')
            or 'Unknown'
        )
        description = data.get('description', '')
        niche = self._classify_niche(title, description)
        content_quality = self._assess_harvester_quality(data)

        return ChannelMetrics(
            username=data.get('username', data.get('handle', '')),
            title=title,
            subscribers=int(data.get('subs', 0)),
            is_public=True,
            is_verified=data.get('is_verified', False),  # Now uses real Bot API data
            description=description,
            recent_posts=int(data.get('posts_per_day', 0)),
            avg_views=float(data.get('avg_views', 0)),
            engagement_rate=round(engagement_rate, 2),
            last_post_date=datetime.now() - timedelta(days=1),
            niche=niche,
            has_profile_photo=True,
            content_quality_score=content_quality,
            total_forwards=int(data.get('total_forwards', 0)),
            total_reactions=int(data.get('total_reactions', 0)),
            media_ratio=float(data.get('media_ratio', 0.0)),
            posts_per_day=float(data.get('posts_per_day', 0.0)),
        )

    def _extract_subscribers(self, data: Dict) -> int:
        """Extract subscriber count from various API formats"""
        subscriber_fields = [
            'participants_count', 'subscribers_count', 'member_count', 
            'subscribers', 'members', 'participants', 'count', 'subs',
            'participantsCount', 'subscribersCount', 'memberCount'
        ]
        
        for field in subscriber_fields:
            if field in data:
                try:
                    value = data[field]
                    if isinstance(value, (int, float)):
                        return int(value)
                    elif isinstance(value, str):
                        clean_value = value.replace(',', '').replace(' ', '').replace('.', '')
                        return int(clean_value)
                except (ValueError, TypeError):
                    continue
        
        if 'stats' in data and isinstance(data['stats'], dict):
            return self._extract_subscribers(data['stats'])
        
        return 0

    def _parse_last_post_date(self, data: Dict) -> datetime:
        """Parse last post date from various formats"""
        date_fields = ['last_post', 'lastPost', 'last_activity', 'updated_at']
        
        for field in date_fields:
            if field in data and data[field]:
                try:
                    date_str = data[field]
                    if isinstance(date_str, str):
                        for fmt in ['%Y-%m-%d', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S']:
                            try:
                                return datetime.strptime(date_str[:len(fmt)], fmt)
                            except ValueError:
                                continue
                except Exception:
                    continue
        
        return datetime.now() - timedelta(days=1)

    def _assess_telemetrio_quality(self, data: Dict) -> float:
        """Assess content quality from Telemetr.io metrics"""
        score = 0.5
        
        avg_views = data.get('avg_views', 0)
        subscribers = self._extract_subscribers(data)
        if subscribers > 0:
            engagement_rate = (avg_views / subscribers) * 100
            if engagement_rate > 30:
                score += 0.3
            elif engagement_rate > 15:
                score += 0.2
        
        recent_posts = data.get('posts_last_week', 0)
        if recent_posts >= 7:
            score += 0.2
        elif recent_posts >= 3:
            score += 0.1
        
        if data.get('verified', False):
            score += 0.2
        
        if data.get('description') and len(data.get('description', '')) > 50:
            score += 0.1
        
        return min(score, 1.0)

    def _assess_harvester_quality(self, data: Dict) -> float:
        """Assess content quality from Harvester metrics"""
        score = 0.5
        
        # Engagement rate bonus
        subs = data.get('subs', 0)
        avg_views = data.get('avg_views', 0)
        if subs > 0 and avg_views > 0:
            engagement_rate = (avg_views / subs) * 100
            if engagement_rate > 30:
                score += 0.3
            elif engagement_rate > 15:
                score += 0.2
        
        # Posting frequency bonus
        posts_per_day = data.get('posts_per_day', 0)
        if posts_per_day >= 1:
            score += 0.2
        elif posts_per_day >= 0.5:
            score += 0.1
        
        # Media content bonus
        media_ratio = data.get('media_ratio', 0)
        if media_ratio > 0.5:
            score += 0.1
        
        # Engagement interaction bonus
        total_reactions = data.get('total_reactions', 0)
        total_forwards = data.get('total_forwards', 0)
        if total_reactions > 0 or total_forwards > 0:
            score += 0.1
        
        # Verification bonus
        if data.get('is_verified', False):
            score += 0.2
        
        return min(score, 1.0)

    def _classify_niche(self, title: str, description: str) -> ChannelNiche:
        """Classify channel niche based on content"""
        text = (title + ' ' + description).lower()
        keywords = {
            ChannelNiche.CRYPTO: ['crypto', 'bitcoin', 'blockchain', 'defi', 'nft', 'trading', 'altcoin'],
            ChannelNiche.TECH: ['tech', 'technology', 'programming', 'ai', 'software', 'developer'],
            ChannelNiche.BUSINESS: ['business', 'entrepreneur', 'startup', 'marketing', 'sales'],
            ChannelNiche.FINANCE: ['finance', 'investment', 'stock', 'forex', 'money'],
            ChannelNiche.NEWS: ['news', 'breaking', 'daily', 'update', 'current'],
            ChannelNiche.GAMING: ['gaming', 'game', 'esports', 'gamer'],
            ChannelNiche.EDUCATION: ['education', 'learning', 'course', 'tutorial'],
            ChannelNiche.ENTERTAINMENT: ['entertainment', 'fun', 'meme', 'funny'],
        }
        
        for niche, niche_keywords in keywords.items():
            if any(keyword in text for keyword in niche_keywords):
                return niche
        return ChannelNiche.ENTERTAINMENT

# Eligibility Checker
class EligibilityChecker:
    def __init__(self, config: Config):
        self.config = config

    async def check_eligibility(self, metrics: ChannelMetrics) -> EligibilityResult:
        reasons = []
        warnings = []
        eligible = True
        confidence = 1.0

        if not metrics.is_public:
            eligible = False
            reasons.append("❌ Channel must be public")

        if metrics.subscribers < self.config.MIN_SUBSCRIBERS:
            eligible = False
            reasons.append(f"❌ Needs {self.config.MIN_SUBSCRIBERS}+ subscribers (has {metrics.subscribers})")

        # Fix timezone issue for date comparison
        now = datetime.now()
        last_post = metrics.last_post_date
        if last_post.tzinfo is not None:
            last_post = last_post.replace(tzinfo=None)
        if now.tzinfo is not None:
            now = now.replace(tzinfo=None)
            
        days_since_last_post = (now - last_post).days
        if days_since_last_post > self.config.ACTIVITY_DAYS:
            eligible = False
            reasons.append(f"❌ No activity in last {self.config.ACTIVITY_DAYS} days")

        if not metrics.has_profile_photo:
            warnings.append("⚠️ Missing profile photo")
            confidence -= 0.1

        if not metrics.description:
            warnings.append("⚠️ Missing channel description")
            confidence -= 0.1

        if metrics.engagement_rate < 10:
            warnings.append("⚠️ Low engagement rate (<10%)")
            confidence -= 0.2

        if metrics.content_quality_score < 0.3:
            warnings.append("⚠️ Low content quality score")
            confidence -= 0.1

        if eligible:
            reasons.append("✅ Meets basic Telegram ads requirements")

        return EligibilityResult(
            eligible=eligible,
            reasons=reasons,
            warnings=warnings,
            confidence=max(confidence, 0.0)
        )

# Enhanced CPM Calculator
class CPMCalculator:
    def __init__(self, config: Config):
        self.config = config
        self.niche_multipliers = {
            ChannelNiche.CRYPTO: 1.4,
            ChannelNiche.FINANCE: 1.3,
            ChannelNiche.TECH: 1.2,
            ChannelNiche.BUSINESS: 1.1,
            ChannelNiche.GAMING: 1.0,
            ChannelNiche.EDUCATION: 0.9,
            ChannelNiche.NEWS: 0.8,
            ChannelNiche.ENTERTAINMENT: 0.7,
            ChannelNiche.LIFESTYLE: 0.8,
        }
        self.subscriber_tiers = [
            (1000, 0.15),
            (10000, 0.25),
            (50000, 0.45),
            (100000, 0.75),
        ]

    async def calculate_cpm(self, metrics: ChannelMetrics, eligibility: EligibilityResult) -> CPMRecommendation:
        base_cpm = self._get_base_cpm(metrics.subscribers)
        niche_multiplier = self.niche_multipliers.get(metrics.niche, 1.0)
        engagement_multiplier = self._get_engagement_multiplier(metrics.engagement_rate)
        quality_multiplier = 0.8 + (metrics.content_quality_score * 0.4)
        verification_multiplier = 1.1 if metrics.is_verified else 1.0
        
        # Enhanced multipliers from harvester data
        interaction_multiplier = self._get_interaction_multiplier(metrics)
        frequency_multiplier = self._get_frequency_multiplier(metrics.posts_per_day)
        
        final_multiplier = (niche_multiplier * engagement_multiplier * quality_multiplier * 
                          verification_multiplier * interaction_multiplier * frequency_multiplier)
        competitive_cpm = base_cpm * final_multiplier
        
        conservative_cpm = max(competitive_cpm * 0.8, self.config.MIN_CPM_TON)
        competitive_cpm = max(competitive_cpm, self.config.MIN_CPM_TON)
        aggressive_cpm = max(competitive_cpm * 1.3, self.config.MIN_CPM_TON)
        
        reasoning = self._generate_reasoning(metrics, base_cpm, final_multiplier)
        market_position = self._assess_market_position(metrics)
        success_probability = eligibility.confidence * 0.7 if eligibility.eligible else 0.1
        
        return CPMRecommendation(
            conservative=round(conservative_cpm, 2),
            competitive=round(competitive_cpm, 2),
            aggressive=round(aggressive_cpm, 2),
            reasoning=reasoning,
            market_position=market_position,
            success_probability=success_probability
        )

    def _get_interaction_multiplier(self, metrics: ChannelMetrics) -> float:
        """Calculate multiplier based on harvester interaction metrics"""
        if metrics.total_reactions == 0 and metrics.total_forwards == 0:
            return 1.0  # No penalty if data not available
        
        # Calculate interaction rate per view
        total_interactions = metrics.total_reactions + metrics.total_forwards
        if metrics.avg_views > 0:
            interaction_rate = total_interactions / (metrics.avg_views * 100)  # Per 100 messages
            
            if interaction_rate > 10:
                return 1.2  # High interaction
            elif interaction_rate > 5:
                return 1.1  # Good interaction
            elif interaction_rate < 1:
                return 0.95  # Low interaction
        
        return 1.0

    def _get_frequency_multiplier(self, posts_per_day: float) -> float:
        """Calculate multiplier based on posting frequency"""
        if posts_per_day == 0:
            return 1.0  # No penalty if data not available
        
        if posts_per_day >= 2:
            return 1.1  # Very active
        elif posts_per_day >= 1:
            return 1.05  # Active
        elif posts_per_day >= 0.5:
            return 1.0  # Regular
        else:
            return 0.95  # Inactive

    def _get_base_cpm(self, subscribers: int) -> float:
        for threshold, cpm in reversed(self.subscriber_tiers):
            if subscribers >= threshold:
                return cpm
        return self.subscriber_tiers[0][1]

    def _get_engagement_multiplier(self, engagement_rate: float) -> float:
        if engagement_rate >= 50:
            return 1.3
        elif engagement_rate >= 30:
            return 1.15
        elif engagement_rate >= 20:
            return 1.0
        elif engagement_rate >= 10:
            return 0.9
        else:
            return 0.8

    def _generate_reasoning(self, metrics: ChannelMetrics, base_cpm: float, multiplier: float) -> str:
        factors = []
        tier_name = self._get_tier_name(metrics.subscribers)
        factors.append(f"Base ({tier_name}): {base_cpm} TON")
        
        if metrics.engagement_rate >= 30:
            factors.append(f"High engagement (+{int((self._get_engagement_multiplier(metrics.engagement_rate) - 1) * 100)}%)")
        elif metrics.engagement_rate < 20:
            factors.append(f"Low engagement ({int((1 - self._get_engagement_multiplier(metrics.engagement_rate)) * 100)}% discount)")
        
        niche_mult = self.niche_multipliers.get(metrics.niche, 1.0)
        if niche_mult > 1.0:
            factors.append(f"{metrics.niche.value.title()} niche premium (+{int((niche_mult - 1) * 100)}%)")
        elif niche_mult < 1.0:
            factors.append(f"{metrics.niche.value.title()} niche discount ({int((1 - niche_mult) * 100)}%)")
        
        # Enhanced factors from harvester data
        if metrics.posts_per_day >= 1:
            factors.append(f"High activity ({metrics.posts_per_day:.1f} posts/day)")
        
        if metrics.total_reactions > 0 or metrics.total_forwards > 0:
            factors.append("Good interaction metrics")
        
        if metrics.content_quality_score > 0.7:
            factors.append("High content quality")
        elif metrics.content_quality_score < 0.4:
            factors.append("Content quality concerns")
        
        if metrics.is_verified:
            factors.append("Verified channel (+10%)")
        
        return " • ".join(factors)

    def _get_tier_name(self, subscribers: int) -> str:
        if subscribers >= 100000:
            return "100K+ tier"
        elif subscribers >= 50000:
            return "50K-100K tier"
        elif subscribers >= 10000:
            return "10K-50K tier"
        else:
            return "1K-10K tier"

    def _assess_market_position(self, metrics: ChannelMetrics) -> str:
        if metrics.engagement_rate >= 40 and metrics.subscribers >= 50000:
            return "Premium channel - high competition expected"
        elif metrics.engagement_rate >= 25 and metrics.subscribers >= 10000:
            return "Strong performer - competitive market"
        elif metrics.engagement_rate >= 15:
            return "Average performer - moderate competition"
        else:
            return "Below average - easier entry but lower ROI"

# Market Data Collector
class MarketDataCollector:
    def __init__(self):
        self.ton_price_url = "https://api.coingecko.com/api/v3/simple/price?ids=the-open-network&vs_currencies=usd"

    async def get_ton_price(self) -> float:
        try:
            response = requests.get(self.ton_price_url, timeout=10)
            data = response.json()
            return data['the-open-network']['usd']
        except Exception as e:
            logger.error(f"Failed to get TON price: {e}")
            return 5.0

# Main Bot Class
class CPMRecommendationBot:
    def __init__(self, config: Config):
        self.config = config
        self.bot = telebot.TeleBot(config.BOT_TOKEN)
        self.firebase_manager = FirebaseManager(config.FIREBASE_CREDENTIALS_PATH)
        self.channel_analyzer = ChannelAnalyzer(config)
        self.eligibility_checker = EligibilityChecker(config)
        self.cpm_calculator = CPMCalculator(config)
        self.market_collector = MarketDataCollector()
        self._last_requests = {}
        self.setup_handlers()

    def setup_handlers(self):
        @self.bot.message_handler(commands=['start'])
        def start_command(message):
            welcome_text = """🎯 *Telegram Ads Helper* - Enhanced CPM Analysis Expert

I analyze Telegram channels with comprehensive data sources and provide optimal CPM recommendations.

*Commands:*
• `/analyze @channel` - Deep channel analysis with engagement metrics
• `/find crypto` - Discover monetized channels by niche
• `/market finance` - Get current market rates for a niche
• `/help` - Show detailed help

*Data Sources:*
📊 Telemetr.io integration for premium analytics
🔍 Advanced harvester for detailed engagement metrics
🤖 Bot API for real verification status and descriptions
📈 TGStat.ru for comprehensive channel coverage
💰 Real-time TON pricing and market intelligence

*Try it now:*
`/analyze @channelname` - See comprehensive analysis with real verification data!"""
            self.bot.reply_to(message, welcome_text, parse_mode='Markdown')

        @self.bot.message_handler(commands=['help'])
        def help_command(message):
            help_text = """🔍 *Enhanced CPM Recommendation Bot Guide*

*Channel Analysis Features:*
• **Multi-source data**: Telemetr.io + Harvester + Bot API + TGStat
• **Real verification status**: Via Bot API integration
• **Engagement metrics**: Views, reactions, forwards, media ratio
• **Activity analysis**: Posts per day, content quality scoring
• **Market positioning**: Premium/competitive/budget tiers

*Analysis Command:*
`/analyze @channelname` - Get comprehensive analysis including:
• Real verification status (Bot API)
• Real channel descriptions (Bot API)
• Subscriber count and engagement rates (Multi-source)
• Content quality and posting frequency (Harvester)
• Interaction metrics (reactions, forwards) (Harvester)
• CPM recommendations (Conservative/Competitive/Aggressive)
• Success probability and market positioning

*Enhanced Metrics:*
• 📊 **Engagement Rate**: Average views vs subscribers
• 🔄 **Interaction Rate**: Reactions + forwards per message
• 📱 **Media Ratio**: Visual content percentage
• ⏰ **Activity Level**: Posts per day analysis
• ✅ **Real Verification**: From Telegram Bot API
• 🎯 **Content Quality**: Multi-factor scoring algorithm

*Market Intelligence:*
`/market finance` - Niche-specific rates and trends
`/find crypto` - Channel discovery guidance

*Success Tips:*
• Target channels with 20%+ engagement rates
• Look for regular posting schedules (0.5+ posts/day)
• Consider interaction metrics for audience quality
• Build relationships before placing ads"""
            self.bot.reply_to(message, help_text, parse_mode='Markdown')

        @self.bot.message_handler(commands=['analyze'])
        def analyze_command(message):
            def run_async():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self.analyze_channel_command(message))
                loop.close()
            
            thread = threading.Thread(target=run_async)
            thread.start()

        @self.bot.message_handler(commands=['find'])
        def find_command(message):
            def run_async():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self.find_channels_command(message))
                loop.close()
            
            thread = threading.Thread(target=run_async)
            thread.start()

        @self.bot.message_handler(commands=['market'])
        def market_command(message):
            def run_async():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self.market_rates_command(message))
                loop.close()
            
            thread = threading.Thread(target=run_async)
            thread.start()

    async def analyze_channel_command(self, message):
        """Enhanced channel analysis with comprehensive metrics"""
        try:
            # Rate limiting
            user_id = message.from_user.id
            now = datetime.now()
            
            if user_id in self._last_requests:
                time_diff = (now - self._last_requests[user_id]).seconds
                if time_diff < 60:
                    self.bot.reply_to(message, 
                        f"⏳ Please wait {60-time_diff} seconds before next analysis.")
                    return
            
            self._last_requests[user_id] = now
            
            # Extract channel username
            text = message.text.split()
            if len(text) < 2:
                self.bot.reply_to(message, "❌ Please provide a channel username.\nExample: `/analyze @channelname`", parse_mode='Markdown')
                return

            channel_username = text[1].lstrip('@')
            
            # Send processing message
            processing_msg = self.bot.reply_to(message, "🔍 Analyzing channel with enhanced metrics... This may take a moment.")
            
            # Get comprehensive channel metrics
            try:
                metrics = await self.channel_analyzer.analyze_channel(channel_username)
            except Exception as analysis_error:
                error_msg = str(analysis_error).lower()
                if 'flood' in error_msg or 'rate' in error_msg:
                    self.bot.edit_message_text(
                        "⚠️ Rate limit detected. Waiting to protect account integrity.\n"
                        "Try again in a few minutes.",
                        message.chat.id,
                        processing_msg.message_id
                    )
                    return
                else:
                    logger.error(f"Analysis error: {analysis_error}")
                    self.bot.edit_message_text(
                        f"❌ Analysis failed: {str(analysis_error)}",
                        message.chat.id,
                        processing_msg.message_id
                    )
                    return
            
            if not metrics:
                self.bot.edit_message_text(
                    "❌ Channel not found or not accessible. Please check:\n• Channel exists and is public\n• Username is correct\n• Channel is not restricted",
                    message.chat.id,
                    processing_msg.message_id
                )
                return
            
            # Check eligibility
            eligibility = await self.eligibility_checker.check_eligibility(metrics)
            
            # Calculate enhanced CPM
            cpm_rec = await self.cpm_calculator.calculate_cpm(metrics, eligibility)
            
            # Get TON price
            ton_price = await self.market_collector.get_ton_price()
            
            # Generate enhanced response
            response = self.format_enhanced_analysis_response(metrics, eligibility, cpm_rec, ton_price)
            
            # Save to database
            await self.firebase_manager.save_channel_analysis({
                'username': metrics.username,
                'subscribers': metrics.subscribers,
                'niche': metrics.niche.value,
                'eligible': eligibility.eligible,
                'competitive_cpm': cpm_rec.competitive,
                'engagement_rate': metrics.engagement_rate,
                'posts_per_day': metrics.posts_per_day,
                'total_reactions': metrics.total_reactions,
                'total_forwards': metrics.total_forwards,
                'media_ratio': metrics.media_ratio,
                'is_verified': metrics.is_verified
            })
            
            # Send final response
            self.bot.edit_message_text(response, message.chat.id, processing_msg.message_id, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error in analyze command: {e}")
            self.bot.reply_to(message, f"❌ Analysis failed: {str(e)}")

    async def find_channels_command(self, message):
        """Enhanced channel discovery guidance"""
        text = message.text.split()
        if len(text) < 2:
            niches = [niche.value for niche in ChannelNiche]
            self.bot.reply_to(message, 
                f"🔍 *Enhanced Channel Discovery*\n\nUsage: `/find <niche>`\n\nAvailable niches:\n• " + "\n• ".join(niches) + 
                f"\n\n*Example:* `/find crypto`",
                parse_mode='Markdown')
            return

        niche = text[1].lower()
        
        response = f"""🔍 *Find {niche.title()} Channels - Enhanced Strategy*

*Quality Indicators to Look For:*
• 📊 **High engagement**: 20%+ average views/subscribers
• ⏰ **Regular posting**: 0.5+ posts per day
• 💬 **Active community**: Comments, reactions, forwards
• 📱 **Rich media**: Photos, videos, voice messages
• ✅ **Complete profiles**: Description, photo, verification

*Search Strategy:*
1. **Telegram Search**: `{niche}` + "channel", "news", "updates"
2. **Hebrew Keywords**: `{niche} עברית`, `{niche} ישראל` 
3. **Related Terms**: Look for channels in related topics

*Analysis Workflow:*
1. Find potential channels manually
2. Use `/analyze @channel` for comprehensive metrics
3. Look for channels with:
   - 1000+ subscribers
   - 15%+ engagement rate
   - Regular posting schedule
   - Good interaction metrics

*Pro Tips:*
• Target 10-20 channels in your niche
• Build relationships before advertising
• Monitor competitor ad placements
• Test different CPM levels
• Consider direct partnerships for premium channels

*Quality Benchmarks:*
• **Premium**: 30%+ engagement, daily posts, high interactions
• **Good**: 20%+ engagement, 3+ posts/week, some interactions  
• **Average**: 10%+ engagement, weekly posts, basic metrics"""
        
        self.bot.reply_to(message, response, parse_mode='Markdown')

    async def market_rates_command(self, message):
        """Enhanced market rates with comprehensive data"""
        text = message.text.split()
        niche = text[1].lower() if len(text) > 1 else 'general'
        
        ton_price = await self.market_collector.get_ton_price()
        
        niche_enum = None
        for n in ChannelNiche:
            if n.value == niche:
                niche_enum = n
                break
        
        multiplier = self.cpm_calculator.niche_multipliers.get(niche_enum, 1.0) if niche_enum else 1.0
        
        response = f"""📊 *Enhanced Market Analysis - {niche.title()} Niche*

💰 *Current TON Price:* ${ton_price:.2f}

📈 *Base CPM Tiers (TON):*
• **1K-10K subscribers**: 0.15-0.25 TON (${0.15*ton_price:.2f}-${0.25*ton_price:.2f})
• **10K-50K subscribers**: 0.25-0.45 TON (${0.25*ton_price:.2f}-${0.45*ton_price:.2f})
• **50K-100K subscribers**: 0.45-0.75 TON (${0.45*ton_price:.2f}-${0.75*ton_price:.2f})
• **100K+ subscribers**: 0.75+ TON (${0.75*ton_price:.2f}+)

🎯 *{niche.title()} Niche Multiplier:* {multiplier:.1f}x
• **Adjusted ranges**: {0.15*multiplier:.2f}-{0.75*multiplier:.2f} TON

🔥 *Quality Premiums:*
• **High engagement** (30%+): +15% CPM
• **Daily posting**: +10% CPM
• **Rich interactions**: +10% CPM
• **Verified channels**: +10% CPM
• **Premium content**: +20% CPM

⚠️ *Market Realities:*
• Channel owner must manually enable ads
• Advertisers select channels manually
• Success depends on relationship building
• Quality content increases acceptance rates

*Bidding Strategy:*
• **Conservative**: Base rate × 0.8 (higher acceptance)
• **Competitive**: Base rate × 1.0 (balanced approach)
• **Aggressive**: Base rate × 1.3 (premium placement)

*Success Metrics:*
• Aim for 15%+ acceptance rate
• Monitor cost per actual impression
• Track conversion rates from ads
• Build long-term channel relationships"""
        
        self.bot.reply_to(message, response, parse_mode='Markdown')

    def format_enhanced_analysis_response(self, metrics: ChannelMetrics, eligibility: EligibilityResult, cpm_rec: CPMRecommendation, ton_price: float) -> str:
        """Format comprehensive analysis with enhanced metrics"""
        
        status_icon = "✅" if eligibility.eligible else "❌"
        
        # Enhanced engagement tiers
        if metrics.engagement_rate >= 40:
            engagement_tier = "🚀 Outstanding"
        elif metrics.engagement_rate >= 30:
            engagement_tier = "🔥 Excellent"
        elif metrics.engagement_rate >= 20:
            engagement_tier = "⭐ Good"
        elif metrics.engagement_rate >= 10:
            engagement_tier = "📊 Average"
        else:
            engagement_tier = "📉 Low"

        # Activity level assessment
        if metrics.posts_per_day >= 2:
            activity_level = "🔥 Very Active"
        elif metrics.posts_per_day >= 1:
            activity_level = "⭐ Active"
        elif metrics.posts_per_day >= 0.5:
            activity_level = "📊 Regular"
        else:
            activity_level = "📉 Low Activity"

        # USD conversions
        conservative_usd = cpm_rec.conservative * ton_price
        competitive_usd = cpm_rec.competitive * ton_price
        aggressive_usd = cpm_rec.aggressive * ton_price

        response = f"""🎯 *Enhanced CPM Analysis: @{metrics.username}*

{status_icon} *Eligibility:* {"ELIGIBLE" if eligibility.eligible else "NOT ELIGIBLE"}

📊 *Core Metrics:*
• **Subscribers**: {metrics.subscribers:,}
• **Avg Views**: {metrics.avg_views:,.0f}
• **Engagement**: {metrics.engagement_rate:.1f}% {engagement_tier}
• **Niche**: {metrics.niche.value.title()}
• **Verified**: {"✅" if metrics.is_verified else "❌"}
• **Description**: {metrics.description[:100] + "..." if len(metrics.description) > 100 else metrics.description}

🔍 *Advanced Analytics:*
• **Activity**: {metrics.posts_per_day:.1f} posts/day {activity_level}
• **Media Content**: {metrics.media_ratio*100:.0f}% visual posts
• **Community Interaction**: {metrics.total_reactions:,} reactions
• **Viral Content**: {metrics.total_forwards:,} forwards
• **Last Post**: {self.format_time_ago(metrics.last_post_date)}

🎯 *Eligibility Assessment:*"""
        
        for reason in eligibility.reasons[:3]:
            response += f"  {reason}\n"
        
        if eligibility.warnings:
            response += "\n⚠️ *Key Considerations:*\n"
            for warning in eligibility.warnings[:3]:
                response += f"  {warning}\n"

        if eligibility.eligible:
            response += f"""
💰 *CPM Recommendations:*
• **Conservative**: {cmp_rec.conservative} TON (${conservative_usd:.2f})
• **Competitive**: {cpm_rec.competitive} TON (${competitive_usd:.2f}) ⭐ *Recommended*
• **Aggressive**: {cpm_rec.aggressive} TON (${aggressive_usd:.2f})

🧠 *Pricing Factors:*
{cpm_rec.reasoning}

📈 *Market Position:*
{cpm_rec.market_position}

🎯 *Success Probability:* {cpm_rec.success_probability*100:.0f}%

💡 *Strategic Recommendations:*
• Start with competitive rate for optimal balance
• Monitor acceptance within 48-72 hours
• Consider direct outreach to channel owner
• Track performance vs other channels in niche
• Build relationship for future campaigns

📋 *How Telegram Ads Work:*
• Channel owners must manually enable monetization
• Advertisers manually select specific channels for ads
• Not all eligible channels show ads (owner choice)"""
        else:
            response += f"""
❌ *Not Ready for Telegram Ads*

Focus on channels that meet these criteria:
• ✅ 1000+ subscribers
• ✅ Public and actively posting
• ✅ 15%+ engagement rate
• ✅ Complete channel profile
• ✅ Regular posting schedule

🔍 *Try analyzing established channels in {metrics.niche.value} niche*
*Look for channels with verified status and daily activity*"""

        return response

    def format_time_ago(self, date: datetime) -> str:
        """Format time ago string"""
        now = datetime.now()
        
        # Make both datetimes timezone-naive for comparison
        if date.tzinfo is not None:
            date = date.replace(tzinfo=None)
        if now.tzinfo is not None:
            now = now.replace(tzinfo=None)
            
        delta = now - date
        
        if delta.days > 7:
            return f"{delta.days} days ago"
        elif delta.days > 0:
            return f"{delta.days} days ago"
        elif delta.seconds > 3600:
            hours = delta.seconds // 3600
            return f"{hours} hours ago"
        else:
            minutes = delta.seconds // 60
            return f"{minutes} minutes ago"

    def start_polling(self):
        """Start bot with polling for local PC"""
        logger.info("🚀 Starting Enhanced Telegram CPM Bot in LOCAL PC mode")
        logger.info("📊 Multi-source analysis: Telemetr.io + Harvester + Bot API + TGStat integration")
        logger.info("🔍 Enhanced metrics: Real verification, engagement, interactions, content quality")
        logger.info("🔄 Press Ctrl+C to stop the bot")
        
        try:
            self.bot.remove_webhook()
            self.bot.infinity_polling(timeout=10, long_polling_timeout=5, none_stop=True)
        except KeyboardInterrupt:
            logger.info("👋 Bot stopped by user")
        except Exception as e:
            logger.error(f"❌ Bot polling error: {e}")

# Initialize and start
def main():
    print("🎯 Enhanced Telegram CPM Recommendation Bot")
    print("=" * 60)
    print("📊 Multi-source analysis with Harvester + Bot API + TGStat integration")
    print("🔍 Advanced engagement and interaction metrics")
    print("✅ Real verification status from Bot API")
    print("📈 TGStat.ru for comprehensive channel coverage")
    print()
    
    # Load configuration
    config = Config()
    
    # Validate required credentials
    missing_creds = config.validate()
    
    if missing_creds:
        print("❌ Missing required credentials in .env file:")
        for cred in missing_creds:
            print(f"   • {cred}")
        print()
        print("🔧 Please add these to your .env file:")
        if "BOT_TOKEN" in missing_creds:
            print("   BOT_TOKEN=your_bot_token_from_botfather")
        if "TG_API_ID" in missing_creds or "TG_API_HASH" in missing_creds:
            print("   TG_API_ID=your_id_from_harvester")
            print("   TG_API_HASH=your_hash_from_harvester")
        print()
        print("💡 Get credentials from @BotFather for BOT_TOKEN")
        print("💡 Copy TG_API_ID and TG_API_HASH from your existing harvester setup")
        return
    
    # Check data sources
    data_sources = []
    if config.TELEMETRIO_API_KEY:
        data_sources.append("Telemetr.io")
    if config.HARVESTER_API_ID and config.HARVESTER_API_HASH:
        data_sources.append("Harvester")
    if config.BOT_TOKEN:
        data_sources.append("Bot API")
    if config.TGSTAT_API_TOKEN:
        data_sources.append("TGStat")
    
    if not data_sources:
        print("⚠️ No data sources configured. Bot will have limited functionality.")
        print("💡 Add API keys to .env file for full functionality")
    else:
        print(f"✅ Data sources: {', '.join(data_sources)}")
    
    # Check Firebase
    if not os.path.exists(config.FIREBASE_CREDENTIALS_PATH):
        print(f"⚠️ Firebase credentials not found - running without data persistence")
    else:
        print("✅ Firebase configured for data persistence")
    
    print()
    
    # Initialize and start bot
    try:
        bot_instance = CPMRecommendationBot(config)
        print("✅ Bot initialized successfully")
        bot_instance.start_polling()
        
    except Exception as e:
        print(f"❌ Failed to start bot: {e}")
        logger.error(f"Bot startup error: {e}")

if __name__ == "__main__":
    main()
