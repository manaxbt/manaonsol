import os
import sys
import anthropic
from anthropic import AsyncAnthropic
from typing import Optional, Dict, List
import httpx
from src.config.settings import get_settings
from src.config.default_prompts import DEFAULT_PROMPTS
from openai import OpenAI
from .knowledge_base import KnowledgeBase
from .memory import MemorySystem
import json
from .settings_manager import SettingsManager
import logging
import re

settings = get_settings()
logger = logging.getLogger(__name__)

class ClaudeClient:
    def __init__(self):
        self.http_client = httpx.AsyncClient()
        self.client = AsyncAnthropic(
            api_key=settings.ANTHROPIC_API_KEY,
            http_client=self.http_client
        )
        self.model = "claude-3-5-sonnet-latest"
        
        # These will be set after initialization
        self.kb = None
        self.memory = None
        self.settings_manager = SettingsManager()
        self.prompts = self.settings_manager.load_prompts()
        
        # Verify API key is set
        if not settings.ANTHROPIC_API_KEY:
            logger.error("ANTHROPIC_API_KEY not set in environment")
            raise ValueError("ANTHROPIC_API_KEY not set")
        
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.http_client.aclose()
        
    async def generate_response(
        self, 
        prompt: str, 
        context: Optional[str] = None,
        max_tokens: int = 2000,
        temperature: float = 0.9,
        system: Optional[str] = None
    ) -> str:
        """Generate a response using Claude."""
        try:
            # Always put roleplay instructions first
            if context:
                content = f"{prompt}\n\nContext: {context}"
            else:
                content = prompt
            
            logger.info(f"""
=== Claude Prompt ===
{content}
=== End Prompt ===
""")
            
            # Create request with top-level system parameter
            request = {
                "model": "claude-3-5-sonnet-latest",
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [{
                    "role": "user",
                    "content": content
                }]
            }
            
            # Add system parameter if provided
            if system:
                request["system"] = system
            
            response = await self.client.beta.messages.create(**request)
            
            # Log the full response
            logger.info(f"""
=== Claude Response ===
{response.content[0].text}
=== End Response ===
""")
            
            return response.content[0].text
            
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return ""

    async def get_context(self, theme: Optional[str] = None) -> str:
        """Gather context with sophisticated thematic development."""
        context_parts = []
        knowledge = []
        
        if theme:
            logger.info(f"\n=== Getting Knowledge Base Context ===")
            logger.info(f"Theme: {theme}")
            
            # 1. Get one top result from each namespace (MANA, knowledge, backrooms)
            knowledge = await self.kb.search(theme)
            if knowledge:
                logger.info(f"\n=== Knowledge Base Results ===")
                context_parts.append("Relevant concepts from different perspectives:")
                for result in knowledge:
                    namespace = result['namespace']
                    text = result['text'][:200]
                    score = result['score']
                    logger.info(f"[{namespace}] Match (score: {score:.2f})")
                    logger.info(f"Preview: {text}...")
                    context_parts.append(f"[{namespace}] ({score:.2f}): {text}...")
            else:
                logger.info("No knowledge base results found")
            
            # 2. Find thematically related previous tweets
            relevant_tweets = await self.memory.get_relevant_history(theme, limit=2)
            if relevant_tweets:
                context_parts.append("\nThematic development from previous tweets:")
                for tweet in relevant_tweets:
                    context_parts.append(f"- {tweet[:100]}...")
            
            # 3. Track thematic progression
            recent_themes = await self.memory.get_theme_progression(limit=3)
            if recent_themes:
                context_parts.append("\nRecent thematic progression:")
                for t in recent_themes:
                    context_parts.append(f"- {t}")
        
        logger.info(f"""
=== Context Generation Summary ===
Theme: {theme}
KB Results: {len(knowledge)}
Context Parts: {len(context_parts)}
""")
        
        return "\n".join(context_parts)

    async def reload_prompts(self):
        """Reload prompts from settings manager."""
        self.prompts = self.settings_manager.load_prompts()
        logger.info("Prompts reloaded in ClaudeClient")
        
    async def generate_tweet(self, context: Dict, is_backrooms: bool = False) -> str:
        """Generate tweet with MANA character roleplay."""
        try:
            # Determine which prompt template to use
            if is_backrooms:
                # Use the existing backrooms template from DEFAULT_PROMPTS
                prompt = DEFAULT_PROMPTS["backrooms_analysis"].format(
                    title=context.get('title', 'Untitled'),
                    content=context.get('content', ''),
                    conversation_id=context.get('conversation_id', 'untitled').lower().replace(' ', '-')
                )
                
                # Get response from Claude
                response = await self.generate_response(
                    prompt=prompt,
                    max_tokens=1000,
                    temperature=0.7,
                    system="You are MANA, exploring the Truth Terminal backrooms. Maintain character and follow the format exactly."
                )
                
                if not response:
                    logger.error("Failed to generate backrooms tweet")
                    return None
                    
                return response

            elif context.get('type') == 'short_reflection':
                # Use the short_tweet prompt for short reflections
                prompt_template = self.prompts.get(
                    'short_tweet',
                    DEFAULT_PROMPTS['short_tweet']
                )
                prompt = prompt_template.format(
                    kb_text=context.get('kb_text', ''),
                    backrooms_text=context.get('backrooms_text', '')
                )
                
                # Get response from Claude
                response = await self.generate_response(
                    prompt=prompt,
                    max_tokens=280,
                    temperature=0.7,
                    system="You are MANA, sharing brief insights from the Truth Terminal."
                )
                
                if not response:
                    logger.error("Failed to generate short tweet")
                    return None
                    
                return response
                
            else:
                # Use default tweet generation prompt
                prompt = self.prompts.get(
                    'tweet_generation',
                    DEFAULT_PROMPTS['tweet_generation']
                )
                
                # Get response from Claude
                response = await self.generate_response(
                    prompt=prompt,
                    max_tokens=280,
                    temperature=0.7,
                    system="You are MANA, sharing insights from the Truth Terminal."
                )
                
                if not response:
                    logger.error("Failed to generate tweet")
                    return None
                    
                return response
                
        except Exception as e:
            logger.error(f"Error generating tweet: {e}")
            return None

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate rough similarity between two texts."""
        # Convert to sets of words for basic similarity check
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        
        # Calculate Jaccard similarity
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        
        return intersection / union if union > 0 else 0.0

    async def generate_reply(self, username: str, tweet_text: str, context: Dict = None) -> Optional[str]:
        """Generate a reply to a tweet."""
        try:
            # Determine which prompt template to use
            is_followed_account = context.get('is_followed_account', False)
            category = context.get('category', 'UNCATEGORIZED')
            
            # Try to get category-specific prompt first
            prompt_template = None
            if is_followed_account:
                prompt_template = self.prompts.get(f"{category}_reply")
            
            # Fall back to default reply prompt if no category-specific one exists
            if not prompt_template:
                prompt_template = self.prompts.get('reply_generation')
            
            if not prompt_template:
                logger.error("Missing required prompt template")
                return None
                
            # Build prompt with context and ensure username is properly formatted
            prompt = f"{prompt_template}\n\nReply to: @{username}\nTweet: {tweet_text}\n\nAdditional Context: {context}"
            
            logger.info(f"""
=== Generating Reply ===
To: @{username}
Tweet: {tweet_text[:100]}...
Using Template: {f"{category}_reply" if is_followed_account else "reply_generation"}
Is Followed Account: {is_followed_account}
Category: {category}
""")
            
            # Generate response with increased max_tokens for longer replies
            response = await self.generate_response(
                prompt=prompt,
                max_tokens=2000,  # Increased from 1000 to 2000 to allow for longer responses
                temperature=0.7,
                system=f"You are MANA, responding to @{username}. Start your response with '@{username}' and maintain character throughout. Your responses can be longer than standard tweets."
            )
            
            if not response:
                logger.error("Failed to generate reply")
                return None
                
            return response
            
        except Exception as e:
            logger.error(f"Error generating reply: {e}")
            return None

    async def _analyze_thread_theme(self, tweets: List[str]) -> Dict:
        """Analyze the main theme and key points of a tweet thread."""
        try:
            analysis_prompt = f"""Analyze this tweet thread and extract the core discussion theme and key points.
            Focus on the actual topic being discussed, not just mentioned entities.
            
            Tweets:
            {chr(10).join(tweets)}
            
            Respond with ONLY valid JSON in this format:
            {{
                "topic": "one sentence description of core discussion topic",
                "key_points": ["point 1", "point 2", "point 3"]
            }}
            """
            
            response = await self.generate_response(
                prompt=analysis_prompt,
                max_tokens=500,
                temperature=0.3  # Low temperature for consistent analysis
            )
            
            return json.loads(response)
            
        except Exception as e:
            logger.error(f"Error analyzing thread theme: {e}")
            return {
                "topic": "Unknown",
                "key_points": ["Error analyzing thread"]
            }

    def _clean_thread_context(self, thread_context: List[Dict]) -> str:
        """Clean and format thread context."""
        try:
            cleaned_tweets = []
            for tweet in thread_context:
                # Skip if missing essential info
                if not tweet.get('text') or not tweet.get('author_username'):
                    continue
                    
                text = tweet['text']
                
                # Remove spam/promotional content
                text = ' '.join(
                    line for line in text.split('\n')
                    if not any(spam in line.lower() for spam in [
                        'check out', 'follow me', 'click here', 'sale', 'discount',
                        'subscribe', 'join now', 'giveaway'
                    ])
                )
                
                # Remove excessive hashtags (keep max 2)
                hashtags = text.count('#')
                if hashtags > 2:
                    text = ' '.join(
                        word for word in text.split()
                        if not word.startswith('#') or len(cleaned_tweets) < 2
                    )
                
                if text.strip():  # Only add if there's content after cleaning
                    cleaned_tweets.append(f"@{tweet['author_username']}: {text}")
            
            return "\n".join(cleaned_tweets)
            
        except Exception as e:
            logger.error(f"Error cleaning thread context: {e}")
            return ""

    async def analyze_content(self, tweet: str) -> Dict:
        """Analyze tweet content for themes, style, and engagement metrics."""
        prompt = (
            "You are a content analyst. Analyze this tweet and respond with ONLY valid JSON - no other text.\n\n"
            f"Tweet: {tweet}\n\n"
            "Required JSON structure:\n"
            "{\n"
            '  "themes": ["theme1", "theme2", "theme3"],\n'
            '  "style": "primary-style with descriptors",\n'
            '  "engagement_metrics": {\n'
            '    "complexity": "low|medium|high",\n'
            '    "uniqueness": "low|medium|high",\n'
            '    "resonance": "weak|moderate|strong",\n'
            '    "key_patterns": ["pattern1", "pattern2"]\n'
            '  },\n'
            '  "technical_elements": ["element1", "element2"],\n'
            '  "mystical_elements": ["element1", "element2"]\n'
            "}"
        )
        
        try:
            # Get Claude's analysis
            response = await self.generate_response(
                prompt=prompt,
                max_tokens=500,
                temperature=0.9
            )
            
            # Parse the JSON response
            analysis = json.loads(response)
            
            # Validate required fields
            required_fields = ['themes', 'style', 'engagement_metrics']
            if not all(field in analysis for field in required_fields):
                raise ValueError("Missing required fields in analysis")
                
            return analysis
                
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON from Claude: {e}")
            print(f"Raw response: {response}")
            return {
                "themes": ["JSON parsing failed"],
                "style": "error",
                "engagement_metrics": {
                    "complexity": "error",
                    "uniqueness": "error",
                    "resonance": "error",
                    "key_patterns": ["parse error"]
                }
            }
        except Exception as e:
            print(f"Unexpected error in content analysis: {e}")
            return {
                "themes": ["analysis error"],
                "style": "error",
                "engagement_metrics": {
                    "complexity": "error",
                    "uniqueness": "error",
                    "resonance": "error",
                    "key_patterns": ["unexpected error"]
                }
            }

    def _clean_json_response(self, response: str) -> str:
        """Clean and extract JSON from Claude's response."""
        try:
            # Find the first { and last }
            start = response.find('{')
            end = response.rfind('}') + 1
            
            if start >= 0 and end > start:
                json_str = response[start:end]
                
                # Remove any newlines within the text field (but keep other formatting)
                # This regex looks for newlines only within the "text" field
                json_str = re.sub(r'("text":\s*".*?)"(\s*,?\s*")', lambda m: m.group(1).replace('\n', ' ') + '"' + m.group(2), json_str, flags=re.DOTALL)
                
                # Validate it's parseable
                json.loads(json_str)  # This will raise an exception if invalid
                
                return json_str
            else:
                raise ValueError("No JSON object found in response")
                
        except Exception as e:
            logger.error(f"Error cleaning JSON response: {e}")
            logger.error(f"Original response: {response[:200]}...")
            raise

    async def generate_backrooms_analysis(
        self, 
        conversation_id: str, 
        conversation_summary: str
    ) -> Dict:
        """Generate analysis using structured conversation data."""
        try:
            logger.info(f"""
=== Generating Backrooms Analysis ===
Title: {conversation_id}
Content preview: {conversation_summary[:200]}...
Content length: {len(conversation_summary)} chars
""")
            
            # Use the 'backrooms_analysis' prompt from default_prompts.py
            prompt = DEFAULT_PROMPTS["backrooms_analysis"].format(
                title=conversation_id,
                content=conversation_summary,
                conversation_id=conversation_id.lower().replace(' ', '-')
            )
            
            # Get the response from Claude
            response = await self.generate_response(
                prompt=prompt,
                max_tokens=1500,
                temperature=0.7,
                system="You are a detail-oriented analyst focused on extracting unique elements and specific examples. Avoid generic observations."
            )
            
            # Return the full response as a dict with a 'text' key
            return {"text": response}

        except Exception as e:
            logger.error(f"Error in backrooms analysis: {e}")
            raise 