import os
import json
import re
import urllib.parse
from PIL import Image
from google import genai
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
model_name = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
client = genai.Client(api_key=api_key) if api_key else None

def extract_json_from_response(text: str) -> dict:
    """Extracts valid JSON from markdown fences or raw LLM output."""
    try:
        # Check for ```json ... ``` blocks
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if json_match:
            return json.loads(json_match.group(1))
        return json.loads(text.strip())
    except Exception as e:
        # Fallback dictionary if parsing fails
        return {
            "error": "Failed to parse JSON response",
            "raw_text": text
        }

def build_search_links(category: str, query: str) -> dict:
    """Builds India-specific e-commerce and local service platform search URLs."""
    encoded_q = urllib.parse.quote_plus(query)
    category_lower = category.lower()

    if "home" in category_lower or "furniture" in category_lower or "decor" in category_lower:
        return {
            "Amazon": f"https://www.amazon.in/s?k={encoded_q}",
            "Flipkart": f"https://www.flipkart.com/search?q={encoded_q}",
            "IKEA": f"https://www.ikea.com/in/en/search/?q={encoded_q}"
        }
    elif "party" in category_lower or "catering" in category_lower or "food" in category_lower:
        return {
            "Swiggy": f"https://www.swiggy.com/search?query={encoded_q}",
            "Zomato": f"https://www.zomato.com/search?q={encoded_q}",
            "Amazon": f"https://www.amazon.in/s?k={encoded_q}"
        }
    elif "venue" in category_lower:
        return {
            "OYO": f"https://www.oyorooms.com/search?query={encoded_q}",
            "BookMyShow": f"https://in.bookmyshow.com/explore/events"
        }
    elif "jewelry" in category_lower or "jewellery" in category_lower:
        return {
            "Amazon": f"https://www.amazon.in/s?k={encoded_q}",
            "Flipkart": f"https://www.flipkart.com/search?q={encoded_q}",
            "Melorra": f"https://www.melorra.com/search/?q={encoded_q}",
            "Bluestone": f"https://www.bluestone.com/search?q={encoded_q}"
        }
    return {
        "Amazon": f"https://www.amazon.in/s?k={encoded_q}",
        "Flipkart": f"https://www.flipkart.com/search?q={encoded_q}"
    }

def get_home_recommendations(budget: float, lights: int, fans: int, furniture: int, dining_tables: int, rooms: list, requirements: str) -> dict:
    prompt = f"""
You are PocketSmart AI, an expert home interior planner.
Plan home interior item recommendations for a customer in India within a total budget of INR ₹{budget}.

Specifications:
- Rooms: {', '.join(rooms) if rooms else 'Entire Home'}
- Target items: {lights} lights/fixtures, {fans} ceiling fans, {furniture} furniture pieces, {dining_tables} dining tables
- Additional Requirements: {requirements or 'None'}

Rules:
1. Provide item suggestions strictly in INR (₹). Total estimated price must NOT exceed ₹{budget}.
2. Suggest items accessible on Indian platforms like Amazon India, Flipkart, or IKEA.
3. Respond ONLY in valid JSON matching this structure:
{{
  "total_budget": {budget},
  "allocated_budget": 0.0,
  "remaining_budget": 0.0,
  "budget_breakdown": [
    {{
      "category": "Lighting / Furniture / Appliances",
      "item_name": "Product Name",
      "description": "Brief description",
      "quantity": 1,
      "estimated_price": 0.0,
      "search_term": "keywords to search online"
    }}
  ],
  "styling_tips": [
    "Tip 1", "Tip 2"
  ]
}}
"""
    if client is None:
        raise RuntimeError("Gemini API key is not configured. Add GEMINI_API_KEY to the .env file.")
    response = client.models.generate_content(model=model_name, contents=prompt)
    result = extract_json_from_response(response.text)

    # Attach purchase links
    if "budget_breakdown" in result and isinstance(result["budget_breakdown"], list):
        for item in result["budget_breakdown"]:
            item["shopping_links"] = build_search_links(item.get("category", "home"), item.get("search_term", item.get("item_name", "")))
    return result

def get_party_recommendations(budget: float, guests: int, event_type: str, venue_type: str, needs_catering: bool, needs_decoration: bool, needs_entertainment: bool, requirements: str) -> dict:
    prompt = f"""
You are PocketSmart AI, an event budget planner in India.
Provide party planning recommendations with a total budget of INR ₹{budget}.

Details:
- Event: {event_type}
- Guest Count: {guests}
- Venue Preference: {venue_type}
- Needs Catering: {'Yes' if needs_catering else 'No'}
- Needs Decoration: {'Yes' if needs_decoration else 'No'}
- Needs Entertainment: {'Yes' if needs_entertainment else 'No'}
- Special Requirements: {requirements or 'None'}

Rules:
1. All costs must be in INR (₹) and the sum must not exceed ₹{budget}.
2. Respond ONLY in valid JSON matching this schema:
{{
  "total_budget": {budget},
  "allocated_budget": 0.0,
  "remaining_budget": 0.0,
  "budget_breakdown": [
    {{
      "category": "Catering / Decoration / Entertainment / Venue",
      "description": "Details of the arrangement",
      "allocation": 0.0,
      "search_term": "search keywords"
    }}
  ],
  "venue_suggestions": {{
    "type": "Recommended venue type",
    "capacity": "{guests} guests",
    "estimated_cost": 0.0,
    "search_term": "venue keywords"
  }},
  "additional_suggestions": [
    "Tip 1", "Tip 2"
  ]
}}
"""
    if client is None:
        raise RuntimeError("Gemini API key is not configured. Add GEMINI_API_KEY to the .env file.")
    response = client.models.generate_content(model=model_name, contents=prompt)
    result = extract_json_from_response(response.text)

    if "budget_breakdown" in result and isinstance(result["budget_breakdown"], list):
        for item in result["budget_breakdown"]:
            item["shopping_links"] = build_search_links(item.get("category", "party"), item.get("search_term", ""))
    return result

def get_jewelry_recommendations(budget: float, occasion: str, style_preferences: str, image: Image.Image = None) -> dict:
    base_prompt = f"""
You are PocketSmart AI, a personal stylist and jewelry recommendation specialist in India.
Generate jewelry recommendations with a total budget of INR ₹{budget}.
Occasion: {occasion}
Style Preferences: {style_preferences or 'Modern & Versatile'}

Instructions:
1. Provide matching items (e.g., Necklace, Earrings, Bracelet, Watch/Ring) that stay within the budget of ₹{budget}.
2. Ensure currency is in INR (₹).
3. Respond ONLY in valid JSON matching this structure:
{{
  "total_budget": {budget},
  "outfit_analysis": "Brief comment on how suggestions match the style/color/occasion",
  "jewelry_recommendations": [
    {{
      "item_type": "Necklace / Earrings / Bracelet / Ring",
      "description": "Aesthetic description and pairing notes",
      "estimated_price": 0.0,
      "style": "Contemporary / Ethnic / Minimalist",
      "search_term": "e.g., Gold-toned pearl choker"
    }}
  ],
  "remaining_budget": 0.0,
  "styling_tips": [
    "Tip 1", "Tip 2"
  ]
}}
"""
    if image:
        content = [
            base_prompt + "\nAn outfit image is attached. Analyze color palette, neckline, and aesthetic to match recommendations precisely.",
            image
        ]
        if client is None:
            raise RuntimeError("Gemini API key is not configured. Add GEMINI_API_KEY to the .env file.")
        response = client.models.generate_content(model=model_name, contents=content)
    else:
        if client is None:
            raise RuntimeError("Gemini API key is not configured. Add GEMINI_API_KEY to the .env file.")
        response = client.models.generate_content(model=model_name, contents=base_prompt)

    result = extract_json_from_response(response.text)
    if "jewelry_recommendations" in result and isinstance(result["jewelry_recommendations"], list):
        for item in result["jewelry_recommendations"]:
            item["shopping_links"] = build_search_links("jewelry", item.get("search_term", item.get("item_type", "")))
    return result