# Telegram-Ads-CPM
Recommended CPM calculation for Telegram Ads 
# Telegram CPM Recommendation Bot

A comprehensive Telegram bot for analyzing channels and recommending optimal CPM (Cost Per Mille) rates for advertising campaigns. The bot integrates multiple data sources to provide accurate channel metrics and pricing recommendations.

## Features

### Multi-Source Channel Analysis
- **Telemetr.io Integration**: Premium analytics for detailed channel insights
- **Harvester Integration**: Local cache with advanced engagement metrics
- **Bot API Integration**: Real-time verification status and channel descriptions
- **TGStat Integration**: Comprehensive channel coverage and discovery
- **Real-time TON Pricing**: Live cryptocurrency rates for accurate USD conversion

### Advanced Metrics
- **Engagement Analysis**: Views vs subscribers, interaction rates
- **Content Quality Scoring**: Multi-factor algorithm for content assessment
- **Activity Monitoring**: Posts per day, media ratio, reaction tracking
- **Market Positioning**: Premium, competitive, and budget tier analysis
- **Success Probability**: Confidence scoring for ad placement likelihood

### CPM Recommendations
- **Three-Tier Pricing**: Conservative, Competitive, and Aggressive rates
- **Niche-Specific Multipliers**: Premium rates for crypto, finance, tech verticals
- **Market Intelligence**: Real-time benchmarking and competitor analysis
- **Israeli Market Focus**: Localized pricing recommendations

## Installation

### Prerequisites
- Python 3.8 or higher
- Telegram account
- Bot token from @BotFather

### Quick Start

1. **Clone the repository**
```bash
git clone https://github.com/yourusername/telegram-cpm-bot.git
cd telegram-cpm-bot
```

2. **Install dependencies**
```bash
pip install -r requirements.txt
```

3. **Configure environment**
```bash
cp .env.template .env
# Edit .env with your credentials (see Configuration section)
```

4. **Run the bot**
```bash
python main.py
```

## Configuration

### Required Credentials

Create a `.env` file from `.env.template` and configure:

#### Telegram Bot Token (Required)
```env
BOT_TOKEN=your_bot_token_from_botfather
```
Get from [@BotFather](https://t.me/BotFather):
1. Send `/newbot` to @BotFather
2. Choose bot name and username  
3. Copy the provided token

#### Telegram API Credentials (Required)
```env
TG_API_ID=your_api_id
TG_API_HASH=your_api_hash
```
Get from [my.telegram.org/apps](https://my.telegram.org/apps):
1. Log in with your phone number
2. Create new application
3. Copy API ID and API Hash

### Optional API Keys (Enhanced Features)

#### Telemetr.io (Premium Analytics)
```env
TELEMETRIO_API_KEY=your_telemetr_api_key
```

#### TGStat (Channel Discovery)
```env
TGSTAT_API_TOKEN=your_tgstat_token
```

#### Firebase (Data Persistence)
```env
FIREBASE_CREDENTIALS_PATH=./firebase-credentials.json
```

### Market Configuration (Optional)
```env
MIN_CPM_TON=0.1
MIN_SUBSCRIBERS=1000
ACTIVITY_DAYS=14
```

## Usage

### Bot Commands

#### Channel Analysis
```
/analyze @channelname
```
Get comprehensive channel analysis including:
- Real verification status (Bot API)
- Subscriber count and engagement rates
- Content quality and posting frequency
- Interaction metrics (reactions, forwards)
- CPM recommendations (Conservative/Competitive/Aggressive)
- Success probability and market positioning

#### Channel Discovery
```
/find crypto
```
Get guidance for finding monetized channels by niche with quality indicators and search strategies.

#### Market Intelligence
```
/market finance
```
Get current market rates and niche-specific benchmarks with real-time TON pricing.

### Example Analysis Output

```
Enhanced CPM Analysis: @cryptonews_il

✅ Eligibility: ELIGIBLE

Core Metrics:
• Subscribers: 24,300
• Avg Views: 11,200
• Engagement: 46.1% Excellent
• Niche: Crypto
• Verified: ✅

Advanced Analytics:
• Activity: 2.3 posts/day Very Active
• Media Content: 75% visual posts
• Community Interaction: 450 reactions
• Viral Content: 123 forwards

CPM Recommendations:
• Conservative: 0.42 TON ($2.10)
• Competitive: 0.52 TON ($2.60) ⭐ Recommended
• Aggressive: 0.68 TON ($3.40)

Success Probability: 67%
```

## Architecture

### Data Sources Priority
1. **Telemetr.io** (Premium analytics with detailed metrics)
2. **Harvester + Bot API** (Local cache with real verification)
3. **TGStat** (Comprehensive fallback coverage)

### Core Components
- `ChannelAnalyzer`: Multi-source data integration
- `CPMCalculator`: Advanced pricing algorithms  
- `EligibilityChecker`: Telegram ads requirement validation
- `FirebaseManager`: Data persistence and analytics
- `MarketDataCollector`: Real-time cryptocurrency pricing

### Niche Multipliers
- Crypto: 1.4x
- Finance: 1.3x  
- Tech: 1.2x
- Business: 1.1x
- Gaming: 1.0x
- Education: 0.9x
- News: 0.8x
- Entertainment: 0.7x

## Development

### Local Development
```bash
# Install development dependencies
pip install -r requirements.txt

# Run with debug logging
export LOG_LEVEL=DEBUG
python main.py
```

### Testing Channels
Try analyzing these sample channels:
- `@cryptonews_il` (Crypto news)
- `@techcrunch` (Tech news)
- `@bitcoin` (Cryptocurrency)

### Adding New Data Sources
1. Create new analyzer class in `main.py`
2. Implement `get_channel_data()` method
3. Add to `ChannelAnalyzer.analyze_channel()` priority chain
4. Update configuration in `Config` class

## API Integration

### Telemetr.io
Premium channel analytics with detailed engagement metrics.
- Endpoint: `https://api.telemetr.io/v1`
- Authentication: API Key header
- Rate Limits: Varies by plan

### TGStat.ru
Comprehensive Telegram channel database.
- Endpoint: `https://api.tgstat.ru`
- Authentication: Token header
- Coverage: 1M+ channels

### Bot API
Official Telegram Bot API for real-time data.
- Endpoint: `https://api.telegram.org`
- Use: Verification status, descriptions
- Rate Limits: 30 requests/second

## Deployment

### Local PC (Recommended for Development)
```bash
python main.py
```

### Google Cloud Run
```bash
gcloud run deploy telegram-cpm-bot \
  --source . \
  --platform managed \
  --region us-central1 \
  --memory 512Mi \
  --cpu 1
```

### Docker
```dockerfile
FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "main.py"]
```

## Limitations & Important Notes

### Telegram Ads System Constraints
- Channel owners must manually enable monetization
- Advertisers manually select channels for ads
- No API to detect monetization status
- High-level channels (50+ level) can disable ads entirely

### Workarounds & Best Practices
- Target 10-20 similar channels per campaign
- Build relationships with channel owners
- Test multiple CPM rates across channels
- Manual verification recommended before large campaigns
- Consider direct partnerships for premium channels

### Data Source Limitations
- **Telemetr.io**: Requires subscription, limited free tier
- **Harvester**: Needs local database and API credentials
- **TGStat**: Free tier has request limits
- **Bot API**: Rate limited, no historical data

## Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

### Development Guidelines
- Follow PEP 8 style guide
- Add docstrings for all functions
- Include unit tests for new features
- Update documentation for API changes

## Security

### Credential Management
- Never commit credentials to version control
- Use environment variables for all sensitive data
- Rotate API keys regularly
- Monitor for exposed credentials in logs

### Rate Limiting
- Built-in rate limiting (1 request/minute per user)
- Respectful API usage to prevent blocking
- Automatic backoff for rate limit errors
- User feedback for cooling periods

## Troubleshooting

### Common Issues

**"Missing required credentials"**
- Check `.env` file exists and has correct values
- Verify BOT_TOKEN format: `123456789:ABCdef...`
- Ensure TG_API_ID is numeric

**"Channel not found"**
- Verify channel is public
- Check username spelling (try without @)
- Channel might be restricted or deleted

**"Rate limit detected"**
- Wait for cooldown period (usually 1 hour)
- This protects your account from Telegram restrictions
- Try again later or use different data sources

**"Firebase initialization failed"**
- Check firebase-credentials.json file path
- Verify service account permissions
- Ensure Firestore is enabled in Firebase project

### Debug Mode
Enable detailed logging:
```bash
export LOG_LEVEL=DEBUG
python main.py
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Disclaimer

This bot is for educational and research purposes. Users are responsible for:
- Complying with Telegram's Terms of Service
- Respecting API rate limits and usage policies
- Obtaining proper permissions for commercial use
- Following local advertising and data privacy laws

The authors are not responsible for misuse of this software or any resulting account restrictions.

## Support

- Create an issue for bug reports
- Start a discussion for feature requests
- Check existing issues before posting
- Provide detailed reproduction steps

## Acknowledgments

- Telegram team for the Bot API and MTProto
- Telemetr.io for premium analytics APIs
- TGStat.ru for comprehensive channel database
- Firebase team for data persistence solutions
- Open source community for Python libraries

---

Built for analyzing Telegram advertising opportunities in the Israeli market with TON cryptocurrency integration.
