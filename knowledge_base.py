from typing import List, Dict, Optional
from pinecone import Pinecone
from openai import OpenAI
import numpy as np
from ..config.settings import get_settings
import uuid
import json
from pathlib import Path
import random
import pinecone
import logging
from datetime import datetime

settings = get_settings()
logger = logging.getLogger(__name__)

class KnowledgeBase:
    def __init__(self):
        """Initialize connection to Pinecone and OpenAI."""
        try:
            # Initialize Pinecone
            self.pc = Pinecone(api_key=settings.PINECONE_API_KEY)
            self.index = self.pc.Index(settings.PINECONE_INDEX)
            self.namespace = "knowledge"
            
            # Initialize OpenAI
            self.openai = OpenAI(api_key=settings.OPENAI_API_KEY)
            logger.info(f"Connected to Pinecone index: {settings.PINECONE_INDEX}")
        except Exception as e:
            logger.error(f"Error initializing services: {e}")
            raise

    async def get_embedding(self, text: str) -> List[float]:
        """Generate embedding for text using OpenAI."""
        try:
            logger.info("Attempting to generate embedding with OpenAI...")
            response = self.openai.embeddings.create(
                model="text-embedding-3-small",
                input=text
            )
            # Return the embedding values directly, don't make it awaitable
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            return None

    def _chunk_text(self, text: str, max_tokens: int = 8000) -> List[str]:
        """Split text into chunks that fit within token limits."""
        # Rough estimate: 1 token ≈ 4 characters
        max_chars = max_tokens * 4
        
        if len(text) <= max_chars:
            return [text]
            
        chunks = []
        current_chunk = ""
        
        # Split by paragraphs first
        paragraphs = text.split('\n\n')
        
        for paragraph in paragraphs:
            if len(current_chunk) + len(paragraph) + 2 <= max_chars:
                current_chunk += paragraph + '\n\n'
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = paragraph + '\n\n'
                
        if current_chunk:
            chunks.append(current_chunk.strip())
            
        return chunks

    def _summarize_analysis(self, analysis: Dict) -> Dict:
        """Summarize analysis data to fit within metadata size limits."""
        try:
            # Create a condensed version of the analysis
            summary = {
                'core_concepts': [],
                'narratives': [],
                'unique_elements': [],
                'implications': '',
                'key_quotes': []
            }
            
            # Process core concepts - keep only top 2, limit to 50 chars each
            if 'core_concepts' in analysis:
                concepts = analysis['core_concepts']
                summary['core_concepts'] = [c[:50] for c in concepts[:2]]
            
            # Process narratives - keep only top 1, limit to 75 chars
            if 'narratives' in analysis:
                narratives = analysis['narratives']
                summary['narratives'] = [n[:75] for n in narratives[:1]]
            
            # Process unique elements - keep only top 2, limit to 50 chars each
            if 'unique_elements' in analysis:
                elements = analysis['unique_elements']
                summary['unique_elements'] = [e[:50] for e in elements[:2]]
            
            # Process implications - summarize to key points, limit to 100 chars
            if 'implications' in analysis:
                implications = analysis['implications']
                summary['implications'] = implications[:100] + ('...' if len(implications) > 100 else '')
            
            # Process key quotes - keep only top 1, limit to 75 chars
            if 'key_quotes' in analysis:
                quotes = analysis['key_quotes']
                summary['key_quotes'] = [q[:75] for q in quotes[:1]]
            
            # Verify total size is under 40KB
            summary_json = json.dumps(summary)
            if len(summary_json.encode('utf-8')) > 40000:  # 40KB limit
                logger.warning("Summary still too large, applying additional compression")
                # Further reduce sizes if needed
                for key in summary:
                    if isinstance(summary[key], list):
                        summary[key] = summary[key][:1]  # Keep only first item
                    elif isinstance(summary[key], str):
                        summary[key] = summary[key][:50]  # Limit to 50 chars
            
            return summary
            
        except Exception as e:
            logger.error(f"Error summarizing analysis: {e}")
            return {}

    async def add_document(
        self,
        text: str,
        metadata: Optional[Dict] = None,
        namespace: str = "default"
    ) -> bool:
        """Add a document to the knowledge base."""
        try:
            # Chunk the text if it's too long
            chunks = self._chunk_text(text)
            
            for i, chunk in enumerate(chunks):
                # Create base metadata with essential fields
                chunk_metadata = {
                    'chunk_index': i,
                    'total_chunks': len(chunks),
                    'timestamp': datetime.now().isoformat(),
                    'category': metadata.get('category', '') if metadata else '',
                    'tags': metadata.get('tags', []) if metadata else [],
                    'title': metadata.get('title', '') if metadata else '',
                    'id': metadata.get('id', str(uuid.uuid4())) if metadata else str(uuid.uuid4())
                }
                
                # For backrooms namespace, include summarized analysis data
                if namespace == 'backrooms' and metadata and 'full_analysis' in metadata:
                    analysis = metadata['full_analysis']
                    summarized_analysis = self._summarize_analysis(analysis)
                    chunk_metadata.update(summarized_analysis)
                
                # Generate embedding for this chunk
                embedding = await self.get_embedding(chunk)
                if not embedding:
                    logger.error(f"Failed to generate embedding for chunk {i}")
                    continue
                    
                # Store in Pinecone
                self.index.upsert(
                    vectors=[{
                        'id': f"{chunk_metadata['id']}-{i}",
                        'values': embedding,
                        'metadata': chunk_metadata
                    }],
                    namespace=namespace
                )
                
            return True
            
        except Exception as e:
            logger.error(f"Error adding document: {e}")
            return False

    async def search(
        self,
        query: str,
        top_k: int = 1,
        namespaces: List[str] = ["MANA", "knowledge", "backrooms"]
    ) -> List[Dict]:
        """Search across namespaces, getting top result from each."""
        try:
            logger.info(f"\n=== Knowledge Base Search ===")
            logger.info(f"Query: {query[:100]}...")
            
            vector = await self.get_embedding(query)
            if not vector:
                logger.error("Failed to generate search embedding")
                return []
            
            all_results = []
            for namespace in namespaces:
                response = self.index.query(
                    vector=vector,
                    namespace=namespace,
                    top_k=1,
                    include_metadata=True
                )
                if response.matches:
                    result = response.matches[0]
                    
                    # Process backrooms results differently
                    if namespace == 'backrooms':
                        result_dict = {
                            'text': result.metadata.get('text', ''),
                            'metadata': {
                                'core_concepts': result.metadata.get('full_analysis', {}).get('core_concepts', []),
                                'narratives': result.metadata.get('full_analysis', {}).get('narratives', []),
                                'technical_insights': result.metadata.get('full_analysis', {}).get('technical_insights', []),
                                'key_quotes': result.metadata.get('full_analysis', {}).get('key_quotes', []),
                                'unique_elements': result.metadata.get('unique_elements', []),
                                'implications': result.metadata.get('implications', '')
                            },
                            'score': result.score,
                            'namespace': namespace
                        }
                    else:
                        result_dict = {
                            'text': result.metadata.get('text', ''),
                            'metadata': result.metadata,
                            'score': result.score,
                            'namespace': namespace
                        }
                        
                    all_results.append(result_dict)
                    logger.info(f"""
Found match in {namespace}:
Score: {result.score}
Category: {result.metadata.get('category', 'N/A')}
Unique Elements: {len(result.metadata.get('unique_elements', []))} items
""")
                else:
                    logger.info(f"No matches found in {namespace}")
            
            return all_results
            
        except Exception as e:
            logger.error(f"Error searching: {e}")
            return []

    def get_random_concept(self, namespace: str = None) -> Optional[Dict]:
        """Get a random concept from specified namespace."""
        try:
            # Use provided namespace or default to self.namespace
            target_namespace = namespace or self.namespace
            
            # Generate random vector for better distribution
            random_vector = [random.uniform(-1, 1) for _ in range(1536)]
            
            response = self.index.query(
                vector=random_vector,
                namespace=target_namespace,
                top_k=50,  # Keep reasonable sample size
                include_metadata=True
            )
            
            if not response.matches:
                logger.warning(f"No concepts found for namespace: {target_namespace}")
                return None
                
            # Randomly select one from the results
            concept = random.choice(response.matches)
            
            # Process backrooms concepts differently
            if target_namespace == 'backrooms':
                result = {
                    'id': concept.id,
                    'text': concept.metadata.get('text', ''),
                    'title': concept.metadata.get('title', ''),
                    'namespace': target_namespace,
                    'core_concepts': concept.metadata.get('full_analysis', {}).get('core_concepts', []),
                    'key_quotes': concept.metadata.get('full_analysis', {}).get('key_quotes', []),
                    'unique_elements': concept.metadata.get('unique_elements', []),
                    'implications': concept.metadata.get('implications', '')
                }
            else:
                result = {
                    'id': concept.id,
                    'text': concept.metadata.get('text', ''),
                    'title': concept.metadata.get('title', ''),
                    'namespace': concept.metadata.get('namespace', '')
                }
            
            logger.info(f"""
=== Retrieved Random Concept ===
Namespace: {target_namespace}
ID: {concept.id}
Title: {result['title']}
Unique Elements: {len(result.get('unique_elements', []))} items
""")
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting random concept: {e}")
            return None

    async def get_context_for_topic(self, topic: str) -> str:
        """Get related context from the knowledge namespace."""
        try:
            # Get embeddings for the topic
            topic_embedding = await self.get_embedding(topic)
            if not topic_embedding:  # Check if embedding generation failed
                logger.error("Failed to generate embedding for topic")
                return topic
            
            # Query the knowledge namespace
            response = self.index.query(
                vector=topic_embedding,
                namespace=self.namespace,
                top_k=3,
                include_metadata=True
            )
            
            # Combine the context from related entries
            context = []
            for match in response.matches:
                if match.metadata.get("text"):
                    context.append(match.metadata["text"])
            
            return " ".join(context) if context else topic
            
        except Exception as e:
            logger.error(f"Error getting context: {e}")
            return topic  # Return original topic if context fetch fails

    async def get_total_concepts(self) -> int:
        """Get total number of concepts in the knowledge namespace."""
        try:
            # Get index stats for the knowledge namespace
            stats = self.index.describe_index_stats()
            return stats.namespaces.get(self.namespace, {}).get("vector_count", 0)
        except Exception as e:
            logger.error(f"Error getting total concepts: {e}")
            return 0

    async def get_concept_context(self, concept_id: str, top_k: int = 3) -> List[Dict]:
        """Get expanded context for a concept with metadata."""
        try:
            # Get the original concept first
            concept_response = self.index.fetch(
                ids=[concept_id],
                namespace=self.namespace
            )
            
            if not concept_response.vectors:
                logger.error(f"Could not find original concept with id {concept_id}")
                return []
            
            # Get concept vector and metadata
            concept_vector = concept_response.vectors[concept_id].values
            concept_metadata = concept_response.vectors[concept_id].metadata
            
            # Query similar concepts without strict filtering
            response = self.index.query(
                vector=concept_vector,
                namespace=self.namespace,
                top_k=top_k + 1,  # Add 1 to account for the original concept
                include_metadata=True
            )
            
            # Return list of contexts with their metadata
            contexts = []
            for match in response.matches:
                # Skip if it's the same as the original concept
                if match.id == concept_id:
                    continue
                
                context = {
                    "text": match.metadata.get("text", ""),
                    "score": match.score
                }
                contexts.append(context)
                logger.info(f"Found related context: id={match.id}, score={match.score}")
            
            return contexts
            
        except Exception as e:
            logger.error(f"Error getting concept context: {e}")
            return []

    async def get_documents(self, namespace: str) -> List[Dict]:
        """Get all documents from a namespace."""
        try:
            # Get all vector IDs in the namespace
            stats = self.index.describe_index_stats()
            namespace_stats = stats.namespaces.get(namespace, {})
            vector_count = namespace_stats.get("vector_count", 0)
            
            if vector_count == 0:
                logger.warning(f"No vectors found in namespace: {namespace}")
                return []
            
            logger.info(f"Found {vector_count} vectors in namespace {namespace}")
            
            # Constants
            BATCH_SIZE = 1000
            QUERY_SIZE = 10000  # Increased from 100
            all_docs = []
            all_ids = set()  # Use set to avoid duplicates
            
            # Do multiple queries with different random vectors until we get close to vector_count
            attempts = 0
            max_attempts = 20  # Increased from 2
            
            while len(all_ids) < vector_count and attempts < max_attempts:
                attempts += 1
                random_vector = np.random.rand(1536).tolist()
                response = self.index.query(
                    vector=random_vector,
                    namespace=namespace,
                    top_k=QUERY_SIZE,
                    include_metadata=True
                )
                
                new_ids = [match.id for match in response.matches]
                prev_count = len(all_ids)
                all_ids.update(new_ids)
                new_unique = len(all_ids) - prev_count
                
                logger.info(f"Query {attempts}: Retrieved {len(new_ids)} vectors, {new_unique} new unique IDs (Total unique: {len(all_ids)})")
                
                # If we're not getting many new IDs, try a few more times then break
                if new_unique < 10 and len(all_ids) > vector_count * 0.9:
                    break
            
            all_ids = list(all_ids)
            logger.info(f"Total unique vector IDs retrieved: {len(all_ids)}")
            
            # Fetch documents in batches using their IDs
            for i in range(0, len(all_ids), BATCH_SIZE):
                batch_ids = all_ids[i:i + BATCH_SIZE]
                response = self.index.fetch(
                    ids=batch_ids,
                    namespace=namespace
                )
                
                for id, vector in response.vectors.items():
                    doc = {
                        'id': id,
                        'text': vector.metadata.get('text', ''),
                        'metadata': vector.metadata
                    }
                    all_docs.append(doc)
                
                logger.info(f"Fetched batch of {len(response.vectors)} documents")
            
            logger.info(f"Total documents retrieved: {len(all_docs)}")
            return all_docs
            
        except Exception as e:
            logger.error(f"Error getting documents: {e}")
            raise

    async def delete_document(self, doc_id: str, namespace: str = "knowledge") -> bool:
        """Delete a document from the specified namespace."""
        try:
            self.index.delete(
                ids=[doc_id],
                namespace=namespace
            )
            logger.info(f"Successfully deleted document {doc_id} from namespace {namespace}")
            return True
        except Exception as e:
            logger.error(f"Error deleting document {doc_id}: {e}")
            return False

    async def add_tags(self, doc_id: str, new_tags: List[str], namespace: str = "knowledge") -> bool:
        """Safely add tags to an existing document without modifying other metadata."""
        try:
            # First fetch the existing document
            response = self.index.fetch(ids=[doc_id], namespace=namespace)
            
            if not response.vectors:
                logger.error(f"Document {doc_id} not found")
                return False
            
            # Get existing metadata and tags
            metadata = response.vectors[doc_id].metadata
            existing_tags = set(metadata.get('tags', []))
            
            # Add new tags
            updated_tags = list(existing_tags | set(new_tags))
            
            # Only update if there are new tags
            if len(updated_tags) > len(existing_tags):
                metadata['tags'] = updated_tags
                
                # Update the document with original vector and updated metadata
                self.index.update(
                    id=doc_id,
                    values=response.vectors[doc_id].values,
                    metadata=metadata,
                    namespace=namespace
                )
                
                logger.info(f"Added tags {new_tags} to document {doc_id}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error adding tags to document {doc_id}: {e}")
            return False

    async def find_similar_concepts(self, similarity_threshold: float = 0.8) -> List[Dict]:
        """Find groups of similar concepts in the knowledge base for cleanup."""
        try:
            # Get all concepts
            all_concepts = []
            stats = self.index.describe_index_stats()
            total_vectors = stats.namespaces.get(self.namespace, {}).get("vector_count", 0)
            
            # Fetch in batches of 100
            for i in range(0, total_vectors, 100):
                response = self.index.query(
                    vector=[random.uniform(-1, 1) for _ in range(1536)],
                    namespace=self.namespace,
                    top_k=100,
                    offset=i,
                    include_metadata=True
                )
                all_concepts.extend(response.matches)

            # Find similar groups
            similar_groups = []
            processed_ids = set()

            for i, concept1 in enumerate(all_concepts):
                if concept1.id in processed_ids:
                    continue

                similar_concepts = []  # Reset for each base concept

                for concept2 in all_concepts[i+1:]:  # Start from next concept to avoid self-comparison
                    if concept2.id in processed_ids or concept2.id == concept1.id:  # Skip if already processed or same concept
                        continue
                        
                    similarity = self._calculate_similarity(
                        concept1.metadata.get('text', ''),
                        concept2.metadata.get('text', '')
                    )
                    
                    if similarity > similarity_threshold:
                        similar_concepts.append({
                            'id': concept2.id,
                            'text': concept2.metadata.get('text', '')[:300],
                            'similarity': similarity,
                            'category': concept2.metadata.get('category', ''),
                            'tags': concept2.metadata.get('tags', [])
                        })
                        processed_ids.add(concept2.id)

                if similar_concepts:  # Only add group if we found similar concepts
                    similar_groups.append({
                        'base_concept': {
                            'id': concept1.id,
                            'text': concept1.metadata.get('text', '')[:300],
                            'category': concept1.metadata.get('category', ''),
                            'tags': concept1.metadata.get('tags', [])
                        },
                        'similar_concepts': similar_concepts
                    })
                    processed_ids.add(concept1.id)

            # Log findings
            logger.info(f"""
=== Similar Concepts Analysis ===
Total concepts checked: {total_vectors}
Similar groups found: {len(similar_groups)}
Groups breakdown:
{chr(10).join(f"- Group {i+1}: {len(group['similar_concepts'])+1} concepts" for i, group in enumerate(similar_groups))}
""")

            return similar_groups

        except Exception as e:
            logger.error(f"Error finding similar concepts: {e}")
            return []

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate rough similarity between two texts."""
        # Convert to sets of words for basic similarity check
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        
        # Calculate Jaccard similarity
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        
        return intersection / union if union > 0 else 0.0 