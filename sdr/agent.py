"""
sdr/agent.py
SDR Agent — FastAPI service + Dedalus DedalusRunner orchestration.

Architecture (Agent-as-Tool pattern):
  Coordinator (cheap model) delegates to specialist tools:
    1. research_business — deep web research via Brave Search MCP
    2. draft_proposal — writes a tailored website proposal (strong model)
    3. fact_check_proposal — validates/refines the draft (generator-critic)
    4. call_business — AI phone call via ElevenLabs
    5. classify_conversation — LLM classification of call outcome
    6. send_outreach_email — HTML email via Gmail service account
    7. save_session — persist results to BigQuery
  Callbacks stream progress to the UI Client.
"""

from __future__ import annotations

import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
from fastapi import FastAPI
from dedalus_labs import AsyncDedalus, DedalusRunner
from dotenv import load_dotenv

from common.config import (
    DEFAULT_MODEL,
    RESEARCH_MODEL,
    DRAFT_MODEL,
    CLASSIFIER_MODEL,
    UI_CLIENT_URL,
)
from common.models import (
    AgentCallback,
    AgentType,
    CallOutcome,
    ConversationClassification,
    ProposalDraft,
    SDRRequest,
    SDRResult,
)
from sdr.tools.phone_call import make_phone_call
from sdr.tools.email_tool import send_email
from sdr.tools.bigquery_utils import save_sdr_session, update_lead_status

load_dotenv()
logger = logging.getLogger(__name__)

# In-memory session store
sdr_sessions: dict[str, SDRResult] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("SDR Agent service starting")
    yield
    logger.info("SDR Agent service shutting down")


app = FastAPI(title="SalesShortcut SDR Agent", lifespan=lifespan)


# ── Helper: send callback to UI ─────────────────────────────

async def notify_ui(callback_url: str, payload: AgentCallback):
    url = callback_url or f"{UI_CLIENT_URL}/agent_callback"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json=payload.model_dump())
    except Exception as e:
        logger.warning(f"UI callback failed: {e}")


# ── Specialist Tools (Agent-as-Tool pattern) ─────────────────

async def research_business(business_name: str, city: str, address: str = "") -> str:
    """
    Deep research on a business using web search.
    Examines competitors, reviews, web presence gaps, and market opportunities.
    Returns a detailed research summary.
    """
    client = AsyncDedalus()
    runner = DedalusRunner(client)

    research_prompt = f"""Research this business thoroughly:
Business: {business_name}
City: {city}
Address: {address}

Find:
1. Their online presence (or lack thereof)
2. Competitor businesses nearby that DO have websites
3. Customer reviews and reputation
4. Market gaps and opportunities
5. What type of website would benefit them most

Provide a detailed research report."""

    # Three-tier fallback approach
    
    # Tier 1: Try Brave Search MCP
    try:
        print("🔍 Attempting research with Brave Search MCP...")
        result = await runner.run(
            input=research_prompt,
            model=RESEARCH_MODEL,
            mcp_servers=["windsor/brave-search-mcp"],
            max_steps=5,
        )
        print(f"✅ Research result (Brave Search MCP): {result.final_output}")
        return result.final_output
        
    except Exception as e:
        print(f"❌ Brave Search MCP failed: {e}")
        print("🔍 Falling back to Google Search MCP...")
        
        # Tier 2: Try Google Search MCP
        try:
            result = await runner.run(
                input=research_prompt,
                model=RESEARCH_MODEL,
                mcp_servers=["google-search"],
                max_steps=5,
            )
            print(f"✅ Research result (Google Search MCP): {result.final_output}")
            return result.final_output
            
        except Exception as e2:
            print(f"❌ Google Search MCP also failed: {e2}")
            print("🧠 Falling back to knowledge-based research...")
            
            # Tier 3: Knowledge-based fallback
            try:
                fallback_result = await runner.run(
                    input=f"""Generate a comprehensive research report for this business without web search:
Business: {business_name}
City: {city}
Address: {address}

Based on the business name and type, provide insights on:
1. Likely business category and typical online presence needs
2. Common competitors in this industry that would have websites
3. Typical customer expectations and review patterns for this type of business
4. Market opportunities for businesses in {city}
5. Website features that would benefit this type of business

Use your knowledge of business patterns, local market dynamics, and industry standards.
Be specific and actionable. Format as a detailed research report.""",
                    model=RESEARCH_MODEL,
                    max_steps=3,
                )
                print(f"✅ Research result (Knowledge-based fallback): {fallback_result.final_output}")
                return fallback_result.final_output
                
            except Exception as e3:
                print(f"❌ All research methods failed. Brave: {e}, Google: {e2}, Knowledge: {e3}")
                # Last resort: return a basic template
                return f"""Research Report for {business_name} (Generated from limited data)

BUSINESS OVERVIEW:
- Name: {business_name}
- Location: {city}
- Address: {address}

ONLINE PRESENCE ASSESSMENT:
- Limited information available due to research limitations
- Likely has minimal online presence based on business type
- Opportunity exists for website development

RECOMMENDATIONS:
1. Create a professional website with business information
2. Establish Google My Business listing
3. Develop social media presence
4. Implement online booking/contact system
5. Focus on local SEO for {city} market

NEXT STEPS:
- Contact business to verify current online presence
- Assess specific needs during consultation
- Propose tailored website solution

Note: This report was generated with limited research capabilities. 
A more detailed analysis would be available with full web access."""


async def draft_proposal(business_name: str, research_summary: str) -> str:
    """
    Write a tailored website proposal for a business based on research.
    Returns a structured proposal with value proposition, sections, and pricing.
    """
    client = AsyncDedalus()
    runner = DedalusRunner(client)

    result = await runner.run(
        input=f"""Write a compelling, tailored website proposal for {business_name}.

Research findings:
{research_summary}

Create a proposal with:
1. **Value Proposition**: Why they need a website (use specific data from research)
2. **Proposed Website Sections**: Home, About, Services, Contact, etc. tailored to their business
3. **Key Features**: Online booking, menu display, gallery, testimonials, etc.
4. **Expected Benefits**: More customers, credibility, 24/7 visibility
5. **Pricing Notes**: Competitive pricing suggestions
6. **Timeline**: Estimated delivery

Make it persuasive, specific to their business, and professional.
Return the full proposal text.""",
        model=DRAFT_MODEL,
        max_steps=3,
    )
    return result.final_output


async def fact_check_proposal(proposal_text: str, business_name: str, research_summary: str) -> str:
    """
    Validate and refine a website proposal for accuracy and persuasiveness.
    Acts as a critic — checks claims, improves weak points, ensures professionalism.
    Returns the refined proposal.
    """
    client = AsyncDedalus()
    runner = DedalusRunner(client)

    result = await runner.run(
        input=f"""You are a proposal reviewer and fact-checker. Review this website proposal for {business_name}:

PROPOSAL:
{proposal_text}

ORIGINAL RESEARCH:
{research_summary}

Check for:
1. Accuracy — are all claims supported by the research?
2. Persuasiveness — is the value proposition compelling?
3. Professionalism — tone, grammar, formatting
4. Missing points — anything important left out?
5. Pricing — is it realistic for a small business?

Return the improved, fact-checked version of the full proposal.""",
        model=CLASSIFIER_MODEL,
        max_steps=3,
    )
    return result.final_output


async def classify_call_outcome(transcript: str, business_name: str) -> str:
    """
    Classify the outcome of a phone call based on its transcript.
    Returns JSON with outcome, confidence, key points, and recommended next action.
    """
    print(f"\\n=== CLASSIFICATION START ===")
    print(f"Business: {business_name}")
    print(f"Transcript length: {len(transcript)} chars")
    print(f"Transcript preview: {transcript[:300]}...")
    print(f"CLASSIFIER_MODEL: {CLASSIFIER_MODEL}")
    print("============================\\n")
    
    try:
        client = AsyncDedalus()
        runner = DedalusRunner(client)
        
        print("Starting classification with DedalusRunner...")
        
        result = await runner.run(
            input=f"""Classify this phone call transcript with {business_name}.

TRANSCRIPT:
{transcript}

Classify the outcome as one of these EXACT values:
- "interested": They showed clear interest in a website
- "agreed_to_email": They want more info via email  
- "not_interested": They declined
- "no_answer": No one picked up or voicemail
- "issue_appeared": Technical issue or hostile response
- "other": None of the above

Return a JSON object with these exact keys:
{{
  "outcome": "<one of the exact values above>",
  "confidence": <number between 0.0 and 1.0>,
  "key_points": ["<point1>", "<point2>"],
  "next_action": "<recommended next step>",
  "summary": "<one-sentence summary>"
}}

Return ONLY the JSON, no other text.""",
            model=CLASSIFIER_MODEL,
            max_steps=3,
        )
        
        print(f"Classification result type: {type(result.final_output)}")
        print(f"Classification result: {result.final_output}")
        
        final_result = result.final_output if isinstance(result.final_output, str) else json.dumps(result.final_output)
        print(f"Final classification: {final_result}")
        
        return final_result
        
    except Exception as e:
        print(f"ERROR in classify_call_outcome: {e}")
        print(f"Error type: {type(e)}")
        import traceback
        traceback.print_exc()
        
        # Return a fallback classification
        fallback_result = {
            "outcome": "other",
            "confidence": 0.1,
            "key_points": ["Classification failed"],
            "next_action": "Manual review needed",
            "summary": f"Classification error: {str(e)}"
        }
        return json.dumps(fallback_result)


# ── API Endpoints ────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "sdr", "timestamp": datetime.utcnow().isoformat()}


@app.post("/run_sdr")
async def run_sdr_endpoint(req: SDRRequest):
    """
    Execute the full SDR pipeline for a business lead.
    Research → Proposal → Call → Classify → Email (if interested) → Save.
    """
    session_id = str(uuid.uuid4())
    callback_url = req.callback_url

    await notify_ui(callback_url, AgentCallback(
        agent_type=AgentType.SDR,
        event="sdr_started",
        business_name=req.business_name,
        business_id=req.place_id,
        message=f"Starting SDR outreach for {req.business_name}",
    ))

    try:
        client = AsyncDedalus()
        runner = DedalusRunner(client)

        # Build the coordinator instructions
        # Build step instructions based on skip_call setting
        step4_instruction = "- SKIP THIS STEP - User disabled phone calls" if req.skip_call else f"""- You MUST call: call_business(research_summary, proposal_content)
- Use ACTUAL data from previous steps
- Store result in variable: call_result
- CONFIRM: "✅ STEP 4/7 COMPLETED - Phone call to {req.phone} finished\""""

        step5_instruction = "- SKIP THIS STEP - No call was made" if req.skip_call else f"""- You MUST extract transcript from call_result
- You MUST call: classify_call_outcome(transcript, "{req.business_name}")
- Store result in variable: call_classification
- CONFIRM: "✅ STEP 5/7 COMPLETED - Call outcome classified\""""

        expected_steps = "4 steps" if req.skip_call else "6-7 steps"

        instructions = f"""You are an AI Sales Development Representative (SDR). You MUST execute ALL steps in EXACT order for {req.business_name}.

Business Info:
- Name: {req.business_name}
- Phone: {req.phone}
- Email: {req.email}
- Address: {req.address}
- City: {req.city}
- Context: {req.lead_context}

EXECUTE THESE STEPS IN EXACT ORDER - NO EXCEPTIONS:

STEP 1/7 - RESEARCH:
- You MUST call: research_business("{req.business_name}", "{req.city}", "{req.address}")
- WAIT for complete result
- Store result in variable: research_summary
- CONFIRM: "✅ STEP 1/7 COMPLETED - Research finished"

STEP 2/7 - DRAFT PROPOSAL:  
- You MUST call: draft_proposal("{req.business_name}", research_summary)
- Use the ACTUAL research_summary from step 1
- Store result in variable: proposal_content
- CONFIRM: "✅ STEP 2/7 COMPLETED - Proposal drafted"

STEP 3/7 - FACT-CHECK:
- You MUST call: fact_check_proposal(proposal_content, "{req.business_name}", research_summary)
- Store result in variable: proposal_content (updated)
- CONFIRM: "✅ STEP 3/7 COMPLETED - Proposal fact-checked"

STEP 4/7 - PHONE CALL:
{step4_instruction}

STEP 5/7 - CLASSIFY CALL:
{step5_instruction}

STEP 6/7 - SEND EMAIL:
- IF call outcome is 'interested' or 'agreed_to_email' (OR if calls are skipped):
  - You MUST call: send_outreach_email(subject, html_body, call_transcript)
  - Create professional subject and HTML email
  - CONFIRM: "✅ STEP 6/7 COMPLETED - Email sent"
- ELSE:
  - CONFIRM: "✅ STEP 6/7 COMPLETED - Email not needed based on outcome"

STEP 7/7 - SAVE SESSION:
- You MUST call: save_sdr_result(research_summary, proposal_content, call_transcript, call_outcome, email_result, email_subject)
- Use ALL actual data from previous steps
- CONFIRM: "✅ STEP 7/7 COMPLETED - Session saved to database"

MANDATORY EXECUTION RULES:
1. Execute steps 1, 2, 3, and 7 ALWAYS
2. Execute steps 4 and 5 unless skip_call=True
3. Execute step 6 based on conditions
4. NEVER skip a step without explicit reason
5. CONFIRM each step completion with ✅ message
6. Use ACTUAL data between functions - NO empty strings
7. If any step fails, report error and continue to next step

VERIFICATION:
- You MUST complete exactly {expected_steps}
- You MUST provide ✅ confirmation for each completed step
- Final message MUST list all completed steps"""

        # All specialist tools
        tools = [
            research_business,
            draft_proposal,
            fact_check_proposal,
            classify_call_outcome,
        ]

        # Add phone call tool only if not skipped and phone is available
        if not req.skip_call and req.phone:
            async def call_business(research_context: str, proposal_content: str) -> str:
                """Call the business on the phone with AI voice using research and proposal."""
                print(f"\\n=== PHONE CALL TOOL DEBUG ===")
                print(f"Business: {req.business_name}")
                print(f"Phone: {req.phone}")
                print(f"Research context length: {len(research_context)} chars")
                print(f"Proposal content length: {len(proposal_content)} chars")
                print(f"Research preview: {research_context[:200]}..." if research_context else "EMPTY RESEARCH")
                print(f"Proposal preview: {proposal_content[:200]}..." if proposal_content else "EMPTY PROPOSAL")
                print(f"============================\\n")
                
                return await make_phone_call(
                    phone_number=req.phone,
                    business_name=req.business_name,
                    context=research_context,
                    proposal_summary=proposal_content,
                )
            tools.append(call_business)
 
        # Email tool - always add it but handle missing email gracefully
        async def send_outreach_email(subject: str, html_body: str, call_transcript: str = "") -> str:
            """Send an outreach email to the business."""
            print(f"\\n=== EMAIL TOOL DEBUG ===")
            print(f"Business: {req.business_name}")
            print(f"Original email: {req.email}")
            print(f"Call transcript length: {len(call_transcript)} chars")
            print(f"Subject: {subject}")
            print(f"HTML body length: {len(html_body)} chars")
            print(f"HTML preview: {html_body[:300]}...")
            
            # Try to extract email from transcript if original email is missing
            email_to_use = req.email
            if not email_to_use and call_transcript:
                import re
                
                # Number word mappings for email extraction
                number_words = {
                    # Basic digits
                    'zero': '0', 'one': '1', 'two': '2', 'three': '3', 'four': '4', 
                    'five': '5', 'six': '6', 'seven': '7', 'eight': '8', 'nine': '9',
                    # Teens
                    'ten': '10', 'eleven': '11', 'twelve': '12', 'thirteen': '13', 
                    'fourteen': '14', 'fifteen': '15', 'sixteen': '16', 'seventeen': '17', 
                    'eighteen': '18', 'nineteen': '19',
                    # Tens
                    'twenty': '20', 'thirty': '30', 'forty': '40', 'fifty': '50',
                    'sixty': '60', 'seventy': '70', 'eighty': '80', 'ninety': '90',
                    # Common compound numbers
                    'twenty one': '21', 'twenty two': '22', 'twenty three': '23', 'twenty four': '24', 'twenty five': '25',
                    'twenty six': '26', 'twenty seven': '27', 'twenty eight': '28', 'twenty nine': '29',
                    'thirty one': '31', 'thirty two': '32', 'thirty three': '33', 'thirty four': '34', 'thirty five': '35',
                    'forty two': '42', 'fifty five': '55', 'sixty six': '66', 'seventy seven': '77', 'eighty eight': '88', 'ninety nine': '99',
                    # Alternative spellings
                    'oh': '0', 'nought': '0', 'naught': '0',
                    # Common in email contexts
                    'hundred': '100', 'double zero': '00', 'triple zero': '000'
                }
                
                # Look for email patterns in the transcript with multiple patterns
                email_patterns = [
                    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',  # Standard email
                    r'\b[A-Za-z0-9._%+-]+\s*at\s*[A-Za-z0-9.-]+\s*dot\s*[A-Z|a-z]{2,}\b',  # "john at gmail dot com"
                    r'\b[A-Za-z0-9._%+-]+\s*@\s*[A-Za-z0-9.-]+\s*\.\s*[A-Z|a-z]{2,}\b',  # Spaced email
                    # Complex pattern for "username words numbers at domain dot com"
                    r'\b[A-Za-z0-9._%+-]+(?:\s+(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|\d+))*\s+at\s+[A-Za-z0-9.-]+\s+dot\s+[A-Z|a-z]{2,}\b'
                ]
                
                emails_found = []
                
                # First try standard email pattern
                standard_matches = re.findall(email_patterns[0], call_transcript, re.IGNORECASE)
                emails_found.extend(standard_matches)
                
                # Then try complex spoken email pattern with number words
                complex_pattern = r'\b([A-Za-z0-9._%+-]+(?:\s+(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|\d+))*)\s+at\s+([A-Za-z0-9.-]+)\s+dot\s+([A-Z|a-z]{2,})\b'
                complex_matches = re.findall(complex_pattern, call_transcript, re.IGNORECASE)
                
                for username_part, domain_part, tld_part in complex_matches:
                    # Convert number words to digits in username
                    username_clean = username_part
                    for word, digit in number_words.items():
                        username_clean = re.sub(r'\b' + word + r'\b', digit, username_clean, flags=re.IGNORECASE)
                    username_clean = re.sub(r'\s+', '', username_clean)  # Remove spaces
                    
                    clean_email = f"{username_clean}@{domain_part}.{tld_part}"
                    emails_found.append(clean_email)
                
                # Then try simple "at" and "dot" variations  
                for pattern in email_patterns[1:3]:  # Skip the complex one we handled above
                    matches = re.findall(pattern, call_transcript, re.IGNORECASE)
                    for match in matches:
                        # Clean up "at" and "dot" variations
                        clean_email = re.sub(r'\s*at\s*', '@', match, flags=re.IGNORECASE)
                        clean_email = re.sub(r'\s*dot\s*', '.', clean_email, flags=re.IGNORECASE)
                        clean_email = re.sub(r'\s+', '', clean_email)  # Remove all spaces
                        emails_found.append(clean_email)
                
                if emails_found:
                    email_to_use = emails_found[0]  # Use the first email found
                    print(f"📧 Extracted email from transcript: {email_to_use}")
                    print(f"📝 Available emails found: {emails_found}")
                    # Find the original match in transcript for context
                    for original_match in re.findall(r'[A-Za-z0-9._%+-]+[\s@]*[at@][\s@]*[A-Za-z0-9.-]+[\s.]*[dot.][\s.]*[A-Z|a-z]{2,}', call_transcript, re.IGNORECASE):
                        print(f"📝 Original transcript match: '{original_match}' -> '{email_to_use}'")
                        break
                else:
                    print("❌ No email pattern found in transcript")
                    print(f"📝 Transcript preview: {call_transcript[:500]}...")
                    # Try to find any potential email-like patterns for debugging
                    debug_patterns = [r'[A-Za-z0-9._%+-]+[@at][A-Za-z0-9.-]+[.dot][A-Za-z]{2,}', r'email', r'@', r'gmail', r'yahoo', r'outlook']
                    for debug_pattern in debug_patterns:
                        debug_matches = re.findall(debug_pattern, call_transcript, re.IGNORECASE)
                        if debug_matches:
                            print(f"🔍 Found potential email indicators: {debug_matches}")
                            break
            
            print(f"Final email to use: {email_to_use}")
            print("========================\\n")
            
            if not email_to_use:
                print("No email address available - neither from business data nor transcript")
                return json.dumps({
                    "success": False,
                    "error": f"No email address available for {req.business_name}",
                    "message": "Business contact information incomplete and no email provided during call"
                })
            
            try:
                result = await send_email(
                    to_email=email_to_use,
                    subject=subject,
                    html_body=html_body,
                    business_name=req.business_name,
                )
                print(f"Email result: {result}")
                return result
            except Exception as e:
                print(f"EMAIL ERROR: {e}")
                import traceback
                traceback.print_exc()
                return json.dumps({
                    "success": False,
                    "error": str(e),
                    "message": f"Email failed to send to {email_to_use}"
                })
        tools.append(send_outreach_email)

        # Save tool
        def save_sdr_result(
            research_summary: str = "",
            proposal_summary: str = "",
            call_transcript: str = "",
            call_outcome: str = "other",
            email_result: str = "",
            email_subject: str = "",
        ) -> str:
            """Save the SDR session results."""
            print(f"\\n=== SAVE TOOL DEBUG ===")
            print(f"Session ID: {session_id}")
            print(f"Business: {req.business_name}")
            print(f"Place ID: {req.place_id}")
            print(f"Research length: {len(research_summary)} chars")
            print(f"Proposal length: {len(proposal_summary)} chars") 
            print(f"Call transcript length: {len(call_transcript)} chars")
            print(f"Call outcome: {call_outcome}")
            print(f"Email result: {email_result[:200]}..." if email_result else "No email result")
            print(f"Email subject: {email_subject}")
            print("=======================\\n")
            
            try:
                # Parse email result to determine if email was sent successfully
                email_sent = False
                if email_result:
                    try:
                        email_data = json.loads(email_result)
                        email_sent = email_data.get("success", False)
                    except:
                        email_sent = "success" in email_result.lower() and "error" not in email_result.lower()
                
                session_data = {
                    "session_id": session_id,
                    "lead_place_id": req.place_id,
                    "business_name": req.business_name,
                    "research_summary": research_summary[:5000],
                    "proposal_summary": proposal_summary[:5000],
                    "call_transcript": call_transcript[:5000],
                    "call_outcome": call_outcome,
                    "email_sent": email_sent,
                    "email_subject": email_subject,
                    "created_at": datetime.utcnow().isoformat(),
                }
                
                print("Creating SDRResult object...")
                # Update in-memory
                sdr_sessions[session_id] = SDRResult(**session_data)
                print("In-memory update successful")
                
                print("Saving to BigQuery...")
                # Persist to BQ
                result = save_sdr_session(session_data)
                print(f"BigQuery save result: {result}")
                
                return result
                
            except Exception as e:
                print(f"SAVE ERROR: {e}")
                import traceback
                traceback.print_exc()
                return f"Save failed: {str(e)}"

        tools.append(save_sdr_result)

        print(f"\\n=== STARTING DEDALUS RUNNER ===")
        print(f"Business: {req.business_name}")
        print(f"Total tools: {len(tools)}")
        print(f"Max steps: 20")  # Increased from 15
        print(f"Model: {DEFAULT_MODEL}")
        print(f"Skip call: {req.skip_call}")
        print("Expected steps: 1=Research, 2=Draft, 3=Fact-check, 4=Call, 5=Classify, 6=Email, 7=Save")
        print("==============================\\n")

        # Initial workflow execution
        result = await runner.run(
            input=instructions,
            model=DEFAULT_MODEL,
            tools=tools,
            max_steps=25,
        )

        final_output = result.final_output if result.final_output else ""
        print(f"Initial workflow completed. Checking step completion...")

        # Define expected confirmations and step retry logic
        expected_confirmations = [
            "✅ STEP 1/7 COMPLETED",
            "✅ STEP 2/7 COMPLETED", 
            "✅ STEP 3/7 COMPLETED",
            "✅ STEP 7/7 COMPLETED"
        ]
        if not req.skip_call:
            expected_confirmations.extend([
                "✅ STEP 4/7 COMPLETED",
                "✅ STEP 5/7 COMPLETED"
            ])
        expected_confirmations.append("✅ STEP 6/7 COMPLETED")

        # Step-specific retry instructions
        step_retry_instructions = {
            "✅ STEP 1/7 COMPLETED": f"You must complete STEP 1/7 - RESEARCH. Call research_business('{req.business_name}', '{req.city}', '{req.address}') and confirm with '✅ STEP 1/7 COMPLETED - Research finished'",
            "✅ STEP 2/7 COMPLETED": f"You must complete STEP 2/7 - DRAFT PROPOSAL. Call draft_proposal('{req.business_name}', research_summary) and confirm with '✅ STEP 2/7 COMPLETED - Proposal drafted'",
            "✅ STEP 3/7 COMPLETED": f"You must complete STEP 3/7 - FACT-CHECK. Call fact_check_proposal(proposal_content, '{req.business_name}', research_summary) and confirm with '✅ STEP 3/7 COMPLETED - Proposal fact-checked'",
            "✅ STEP 4/7 COMPLETED": f"You must complete STEP 4/7 - PHONE CALL. Call call_business(research_summary, proposal_content) and confirm with '✅ STEP 4/7 COMPLETED - Phone call to {req.phone} finished'",
            "✅ STEP 5/7 COMPLETED": f"You must complete STEP 5/7 - CLASSIFY CALL. Extract transcript from call_result, call classify_call_outcome(transcript, '{req.business_name}') and confirm with '✅ STEP 5/7 COMPLETED - Call outcome classified'",
            "✅ STEP 6/7 COMPLETED": f"You must complete STEP 6/7 - SEND EMAIL. Call send_outreach_email(subject, html_body, call_transcript) and confirm with '✅ STEP 6/7 COMPLETED - Email sent'",
            "✅ STEP 7/7 COMPLETED": f"You must complete STEP 7/7 - SAVE SESSION. Call save_sdr_result(research_summary, proposal_content, call_transcript, call_outcome, email_result, email_subject) and confirm with '✅ STEP 7/7 COMPLETED - Session saved to database'"
        }

        # Check for missing steps and retry individually
        max_step_retries = 3
        
        for retry_round in range(max_step_retries):
            missing_steps = []
            for confirmation in expected_confirmations:
                if confirmation not in str(final_output):
                    missing_steps.append(confirmation)
            
            if not missing_steps:
                print(f"🎉 All {len(expected_confirmations)} steps completed successfully!")
                break
                
            print(f"\\n=== STEP RETRY ROUND {retry_round + 1}/{max_step_retries} ===")
            print(f"Missing steps: {[step.split('✅ ')[1].split(' COMPLETED')[0] for step in missing_steps]}")
            
            # Retry each missing step individually
            for missing_step in missing_steps:
                step_name = missing_step.split("✅ ")[1].split(" COMPLETED")[0]
                print(f"\\n🔄 Retrying {step_name}...")
                
                retry_instruction = step_retry_instructions.get(missing_step, f"Complete the missing step: {step_name}")
                
                try:
                    step_result = await runner.run(
                        input=f"""CRITICAL: You must complete this specific step that was missed in the previous workflow.

Previous context available - use any data from previous steps as needed.
Business: {req.business_name}

TASK: {retry_instruction}

You must provide the EXACT confirmation message: {missing_step}

Complete this step now.""",
                        model=DEFAULT_MODEL,
                        tools=tools,
                        max_steps=5,
                    )
                    
                    step_output = step_result.final_output if step_result.final_output else ""
                    
                    if missing_step in step_output:
                        print(f"✅ {step_name} retry successful")
                        final_output += f"\\n\\n{step_output}"
                    else:
                        print(f"❌ {step_name} retry failed - confirmation not found")
                        final_output += f"\\n\\n{step_output}"
                        
                except Exception as e:
                    print(f"❌ {step_name} retry failed with error: {e}")
                    final_output += f"\\n\\nStep retry error for {step_name}: {str(e)}"

        # Final validation
        final_missing_steps = []
        for confirmation in expected_confirmations:
            if confirmation not in str(final_output):
                final_missing_steps.append(confirmation)

        print(f"\\n=== DEDALUS RUNNER COMPLETED ===")
        print(f"Final result length: {len(final_output)} chars")
        
        if final_missing_steps:
            print(f"⚠️  FINAL WARNING: Missing step confirmations: {[step.split('✅ ')[1].split(' COMPLETED')[0] for step in final_missing_steps]}")
        else:
            print(f"✅ All expected steps confirmed in final output")
        print("===============================\\n")

        # Notify UI: completed
        await notify_ui(callback_url, AgentCallback(
            agent_type=AgentType.SDR,
            event="sdr_completed",
            business_name=req.business_name,
            business_id=req.place_id,
            message=f"SDR outreach completed for {req.business_name}",
            data={
                "session_id": session_id,
                "summary": final_output[:1000] if final_output else "",
            },
        ))

        # Update lead status in BQ
        if req.place_id:
            update_lead_status(req.place_id, "contacted")

        return {
            "status": "success",
            "session_id": session_id,
            "business_name": req.business_name,
            "summary": final_output,
        }

    except Exception as e:
        logger.error(f"SDR pipeline failed for {req.business_name}: {e}")
        await notify_ui(callback_url, AgentCallback(
            agent_type=AgentType.SDR,
            event="error",
            business_name=req.business_name,
            message=f"SDR failed: {str(e)}",
        ))
        return {"status": "error", "message": str(e)}


@app.get("/api/sessions")
async def get_sessions():
    return {"sessions": {k: v.model_dump() for k, v in sdr_sessions.items()}}
