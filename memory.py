import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import json
from pathlib import Path
from .knowledge_base import KnowledgeBase
import uuid
from src.core.models import TweetContext

# Configure logging
logger = logging.getLogger(__name__)

class MemorySystem:
    def __init__(self):
        self.kb = KnowledgeBase()
        self.memory_file = Path(__file__).parent.parent / "data" / "tweet_memory.json"
        self.memory_file.parent.mkdir(exist_ok=True)
        self.recent_tweets: List[Dict] = self.load_memory()
        self.max_tweets = 100  # Maximum tweets to keep
        self._is_cleaning = False  # Add flag to prevent recursive cleanup
        self.recent_interactions = []
        self.max_recent_interactions = 1000
        
    def load_memory(self) -> List[Dict]:
        """Load tweet history from file."""
        if self.memory_file.exists():
            with open(self.memory_file, 'r') as f:
                return json.load(f)
        return []
    
    def save_memory(self):
        """Save tweet history to file."""
        with open(self.memory_file, 'w') as f:
            json.dump(self.recent_tweets, f, indent=2)
    
    async def add_tweet(self, tweet: str, context: Optional[str] = None):
        """Store tweet with validation."""
        # Validate tweet format
        if not tweet.startswith("*") or "terminal@backrooms:~/$" not in tweet:
            logger.warning("Invalid tweet format - skipping storage")
            return
        
        # Remove any meta-commentary
        if "Here is an attempt" in tweet or "I tried to" in tweet:
            logger.warning("Meta-commentary detected - skipping storage")
            return
        
        tweet_data = {
            "id": str(uuid.uuid4()),
            "text": tweet,
            "timestamp": datetime.now().isoformat(),
            "context": context
        }
        
        # Store locally
        self.recent_tweets.append(tweet_data)
        self.save_memory()
        logger.debug(f"Tweet stored in local storage: {context}")
        
        try:
            # Store in vector database
            await self.kb.add_document(
                text=tweet,
                metadata={
                    "text": tweet,
                    "timestamp": tweet_data["timestamp"],
                    "context": context,
                    "category": "generated_tweet",
                    "tags": ["mana_tweet"]
                },
                doc_type="tweet"
            )
            logger.debug(f"Tweet added to vector database: {context}")
        except Exception as e:
            logger.error(f"Vector storage addition failed - {str(e)}")
    
    async def get_relevant_history(self, context: str, limit: int = 3) -> List[str]:
        """Get relevant tweets from history."""
        results = await self.kb.search(
            query=context,
            top_k=limit,
            doc_type="tweet"  # Only search tweet namespace
        )
        return [r["text"] for r in results]
    
    def get_recent_tweets(self, limit: int = 5) -> List[str]:
        """Get most recent tweets."""
        return [t["text"] for t in self.recent_tweets[-limit:]]

    async def get_theme_progression(self, limit: int = 3) -> List[str]:
        """Track how themes have developed over recent tweets."""
        recent_tweets = self.recent_tweets[-limit:]
        themes = []
        
        for tweet in recent_tweets:
            # Extract themes from tweet context and content
            context = tweet.get('context', '')
            content = tweet.get('text', '')
            
            # Get related concepts from knowledge base
            results = await self.kb.search(f"{context} {content}", top_k=1)
            if results:
                themes.append({
                    'timestamp': tweet['timestamp'],
                    'main_theme': context,
                    'related_concepts': results[0]['metadata'].get('tags', []),
                    'category': results[0]['metadata'].get('category', '')
                })
        
        return themes

    async def suggest_next_themes(self, current_theme: str) -> List[str]:
        """Suggest potential next themes based on knowledge graph."""
        # Get current theme's related concepts
        results = await self.kb.search(current_theme, top_k=2)
        if not results:
            return []
            
        related_tags = []
        for r in results:
            related_tags.extend(r['metadata'].get('tags', []))
            
        # Find knowledge entries with related tags
        suggestions = []
        for tag in related_tags:
            tag_results = await self.kb.search(tag, top_k=1)
            if tag_results:
                suggestions.append({
                    'theme': tag,
                    'description': tag_results[0]['text'][:100],
                    'category': tag_results[0]['metadata'].get('category')
                })
                
        return suggestions[:3]  # Return top 3 suggested themes 

    async def cleanup_old_tweets(self, days_old: int = 30):
        """Remove tweets older than specified days."""
        if self._is_cleaning:  # Prevent recursive cleanup
            return
            
        self._is_cleaning = True
        try:
            logger.info("Starting tweet cleanup...")
            
            # Clean local storage
            cutoff_date = datetime.now() - timedelta(days=days_old)
            original_count = len(self.recent_tweets)
            
            # Remove duplicates and old tweets
            seen_texts = set()
            cleaned_tweets = []
            for tweet in self.recent_tweets:
                if (datetime.fromisoformat(tweet["timestamp"]) > cutoff_date and 
                    tweet["text"] not in seen_texts):
                    seen_texts.add(tweet["text"])
                    cleaned_tweets.append(tweet)
            
            self.recent_tweets = cleaned_tweets[-self.max_tweets:]
            self.save_memory()
            
            # Reset vector storage without triggering add_tweet
            try:
                self.kb.index.delete(deleteAll=True, namespace="tweet")
                logger.info("Reset tweet namespace in vector storage")
                
                # Direct vector storage without using add_tweet
                for tweet in self.recent_tweets:
                    vector = await self.kb.get_embedding(tweet["text"])
                    self.kb.index.upsert(
                        vectors=[(
                            tweet["id"],
                            vector,
                            {
                                "text": tweet["text"],
                                "timestamp": tweet["timestamp"],
                                "context": tweet.get("context"),
                                "category": "generated_tweet",
                                "tags": ["mana_tweet"]
                            }
                        )],
                        namespace="tweet"
                    )
                
            except Exception as e:
                logger.warning(f"Note: Vector storage cleanup skipped - {str(e)}")
                
        finally:
            self._is_cleaning = False
            
    async def prune_tweet_count(self):
        """Keep only the most recent max_tweets."""
        if len(self.recent_tweets) > self.max_tweets:
            # Remove oldest tweets beyond the limit
            tweets_to_remove = self.recent_tweets[:-self.max_tweets]
            self.recent_tweets = self.recent_tweets[-self.max_tweets:]
            
            # Remove from vector storage
            try:
                for tweet in tweets_to_remove:
                    self.kb.index.delete(
                        filter={"timestamp": tweet["timestamp"]},
                        namespace="tweet"
                    )
            except Exception as e:
                logger.error(f"Error pruning vector storage: {e}")
            
            self.save_memory()
            logger.info(f"Pruned tweets to maintain {self.max_tweets} limit")

    async def get_theme_statistics(self) -> Dict[str, int]:
        """Analyze theme distribution in tweet history."""
        theme_counts = {}
        seen_themes = set()
        
        for tweet in self.recent_tweets:
            # Skip invalid tweets
            if not tweet.get('text', '').startswith('*'):
                continue
            
            theme = tweet.get('context', 'unclassified')
            theme = theme.lower().strip()
            if theme not in seen_themes:
                seen_themes.add(theme)
                # Only count valid tweets
                theme_counts[theme] = sum(
                    1 for t in self.recent_tweets 
                    if t.get('context', '').lower().strip() == theme
                    and t.get('text', '').startswith('*')
                )
        
        return theme_counts 

    async def get_user_interactions(self, author_id: str) -> List[Dict]:
        """Get historical interactions with a specific user."""
        interactions = []
        for tweet in self.recent_tweets:
            if tweet.get('author_id') == author_id:
                interactions.append({
                    'text': tweet['text'],
                    'timestamp': tweet['timestamp'],
                    'quality_score': tweet.get('quality_score', 0.5)
                })
        return interactions

    async def get_recent_user_interactions(self, author_id: str, hours: int = 1) -> List[Dict]:
        """Get recent interactions within specified timeframe."""
        cutoff = datetime.now() - timedelta(hours=hours)
        return [
            tweet for tweet in self.recent_tweets
            if tweet.get('author_id') == author_id
            and datetime.fromisoformat(tweet['timestamp']) > cutoff
        ]

    async def add_interaction(self, tweet: TweetContext, response: str):
        """Store an interaction in memory."""
        try:
            interaction_data = {
                'tweet_id': tweet.tweet_id,
                'author_id': tweet.author_id,
                'author_username': tweet.author_username,
                'tweet_text': tweet.text,
                'response': response,
                'timestamp': tweet.created_at
            }
            
            # Store in memory
            self.recent_interactions.append(interaction_data)
            
            # Trim if too many stored
            if len(self.recent_interactions) > self.max_recent_interactions:
                self.recent_interactions.pop(0)
                
            logger.info(f"Stored interaction for tweet {tweet.tweet_id}")
            
        except Exception as e:
            logger.error(f"Error storing interaction: {str(e)}") 