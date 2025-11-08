from flask import Flask, request, jsonify
from flask_cors import CORS
import anthropic
import httpx
import os
from youtube_transcript_api import YouTubeTranscriptApi
import re

app = Flask(__name__)
CORS(app)

# Configure Anthropic with explicit httpx client to avoid Railway proxy issues
import httpx

# Create httpx client without proxy support to avoid Railway conflicts
http_client = httpx.Client(
    timeout=60.0,
    follow_redirects=True
)

anthropic_client = anthropic.Anthropic(
    api_key=os.getenv('ANTHROPIC_API_KEY'),
    http_client=http_client
)

# In-memory cache for transcripts (in production, use Redis or database)
transcript_cache = {}

def extract_video_id(url):
    """Extract video ID from YouTube URL"""
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
        r'(?:embed\/)([0-9A-Za-z_-]{11})',
        r'(?:watch\?v=)([0-9A-Za-z_-]{11})'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def get_cached_transcript(video_id):
    """Get transcript from cache or fetch and cache it"""
    if video_id in transcript_cache:
        print(f"Using cached transcript for video: {video_id}")
        return transcript_cache[video_id]
    
    try:
        print(f"Fetching new transcript for video: {video_id}")
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        
        # Join all transcript segments
        full_transcript = " ".join([entry['text'] for entry in transcript_list])
        
        # Cache the transcript
        transcript_cache[video_id] = full_transcript
        print(f"Transcript cached successfully for video: {video_id}")
        
        return full_transcript
        
    except Exception as e:
        print(f"Error fetching transcript for {video_id}: {str(e)}")
        return None

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy", 
        "message": "YouTube AI Tutor API is running with Claude",
        "api_key_configured": bool(os.getenv('ANTHROPIC_API_KEY')),
        "cached_videos": len(transcript_cache)
    })

@app.route('/api/tutor/ask', methods=['POST'])
def ask_tutor():
    try:
        data = request.json
        question = data.get('question', '')
        video_title = data.get('videoTitle', '')
        current_time = data.get('currentTime', 0)
        video_id = data.get('videoId', '')
        
        if not question:
            return jsonify({"error": "Question is required"}), 400
        
        print(f"Question received: {question}")
        print(f"Video ID: {video_id}")
        print(f"Video Title: {video_title}")
        
        # Create basic context
        context = f"Video: {video_title}\nCurrent time: {current_time}s"
        
        # Get transcript from cache or fetch it
        video_transcript = ""
        if video_id:
            video_transcript = get_cached_transcript(video_id)
            if video_transcript:
                # Use only relevant portion of transcript to control costs
                context += f"\nTranscript: {video_transcript[:3000]}..."
        
        # Get AI response using Claude
        message = anthropic_client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=800,
            temperature=0.7,
            system="You are a helpful AI tutor. Answer questions about the video content clearly and concisely. If the question relates to a specific time in the video, reference that context. Keep responses focused and educational. Use a friendly, encouraging tone.",
            messages=[
                {
                    "role": "user",
                    "content": f"Context: {context}\n\nQuestion: {question}"
                }
            ]
        )
        
        answer = message.content[0].text
        print(f"AI Response generated successfully")
        
        return jsonify({
            "answer": answer,
            "videoTitle": video_title,
            "currentTime": current_time,
            "cached": video_id in transcript_cache if video_id else False
        })
        
    except Exception as e:
        error_msg = f"Error processing request: {str(e)}"
        print(error_msg)
        return jsonify({"error": error_msg}), 500

@app.route('/api/tutor/transcript', methods=['POST'])
def get_transcript():
    """Endpoint to pre-fetch and cache transcript (optional)"""
    try:
        data = request.json
        video_id = data.get('videoId', '')
        
        if not video_id:
            return jsonify({"error": "Video ID is required"}), 400
        
        # This will cache the transcript if not already cached
        transcript = get_cached_transcript(video_id)
        
        if transcript:
            return jsonify({
                "success": True,
                "message": "Transcript cached successfully",
                "length": len(transcript)
            })
        else:
            return jsonify({"error": "No transcript available for this video"}), 404
        
    except Exception as e:
        print(f"Error in get_transcript: {str(e)}")
        return jsonify({"error": f"Failed to get transcript: {str(e)}"}), 500

@app.route('/api/tutor/cache-status', methods=['GET'])
def cache_status():
    """Check what's currently cached"""
    cached_videos = list(transcript_cache.keys())
    total_size = sum(len(transcript) for transcript in transcript_cache.values())
    
    return jsonify({
        "cached_videos": len(cached_videos),
        "video_ids": cached_videos,
        "total_cache_size": total_size
    })

@app.route('/api/tutor/clear-cache', methods=['POST'])
def clear_cache():
    """Clear transcript cache (useful for development)"""
    global transcript_cache
    cache_size = len(transcript_cache)
    transcript_cache = {}
    return jsonify({
        "message": f"Cache cleared. Removed {cache_size} cached transcripts."
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=False)
