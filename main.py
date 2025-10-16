from flask import Flask, request, jsonify, render_template
import os
import requests
import json
from datetime import datetime
import PyPDF2
import io

app = Flask(__name__)

# OpenRouter Configuration
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', 'your_openrouter_api_key_here')
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEEPSEEK_R1_MODEL = "deepseek/deepseek-r1"

def extract_text_from_pdf(file):
    """Extract text from PDF file"""
    try:
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(file.read()))
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() + "\n"
        return text.strip()
    except Exception as e:
        print(f"Error extracting text from PDF: {e}")
        return None

def analyze_financial_data_with_deepseek(extracted_text):
    """
    Analyze financial data using Deepseek R1 via OpenRouter
    """
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://your-financial-app.com",
        "X-Title": "Financial Due Diligence Tool"
    }
    
    prompt = f"""
    You are a financial analyst. Analyze the following financial documents and provide a comprehensive due diligence report:
    
    {extracted_text}
    
    Please provide a structured analysis covering:
    
    1. FINANCIAL HEALTH ASSESSMENT:
       - Revenue trends and growth patterns
       - Profitability analysis
       - Liquidity position
       - Solvency and leverage
    
    2. KEY FINANCIAL RATIOS:
       - Profitability ratios (Gross Margin, Net Margin, ROE, ROA)
       - Liquidity ratios (Current Ratio, Quick Ratio)
       - Efficiency ratios (Asset Turnover, Inventory Turnover)
       - Leverage ratios (Debt-to-Equity, Debt-to-Assets)
    
    3. TREND ANALYSIS:
       - Year-over-year performance changes
       - Key trends and patterns
       - Seasonal variations if any
    
    4. STRENGTHS AND CONCERNS:
       - Major strengths in financial performance
       - Potential red flags or concerns
       - Areas requiring immediate attention
    
    5. RECOMMENDATIONS:
       - Strategic recommendations
       - Risk mitigation suggestions
       - Opportunities for improvement
    
    Format the response in a clear, professional manner suitable for a due diligence report.
    """
    
    payload = {
        "model": DEEPSEEK_R1_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "max_tokens": 4000,
        "temperature": 0.1
    }
    
    try:
        print("Sending request to Deepseek R1 via OpenRouter...")
        response = requests.post(OPENROUTER_API_URL, headers=headers, json=payload, timeout=120)
        response.raise_for_status()
        
        result = response.json()
        return result['choices'][0]['message']['content']
        
    except requests.exceptions.Timeout:
        print("OpenRouter API timeout")
        return None
    except requests.exceptions.RequestException as e:
        print(f"OpenRouter API error: {e}")
        return None
    except KeyError as e:
        print(f"Unexpected response format: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error: {e}")
        return None

def generate_fallback_report(extracted_texts, file_names):
    """Generate fallback report when AI service is unavailable"""
    total_chars = sum(len(text) for text in extracted_texts.values())
    
    report = {
        "status": "fallback",
        "report_content": f"""
FINANCIAL DUE DILIGENCE REPORT (FALLBACK ANALYSIS)

Total Files Analyzed: {len(file_names)}

Note: Using fallback analysis - AI service unavailable

DOCUMENTS PROCESSED:
{chr(10).join(f'- {name}' for name in file_names)}

TEXT EXTRACTION SUMMARY:
- Successfully extracted text from {len(file_names)} documents
- Total characters processed: {total_chars}
- Documents contain financial data ready for analysis

NEXT STEPS:
1. The system successfully processed all uploaded documents
2. AI analysis service is currently unavailable
3. Please try again later or contact support

For immediate assistance:
- Ensure you have a stable internet connection
- Refresh the page and try again
- Try with fewer documents if the issue persists

Document processing completed at: {datetime.now().strftime('%m/%d/%Y, %I:%M:%S %p')}
""",
        "files_processed": file_names,
        "characters_processed": total_chars,
        "timestamp": datetime.now().isoformat()
    }
    
    return report

def generate_full_report(ai_analysis, extracted_texts, file_names):
    """Generate full report with AI analysis"""
    total_chars = sum(len(text) for text in extracted_texts.values())
    
    report = {
        "status": "success",
        "report_content": f"""
FINANCIAL DUE DILIGENCE REPORT

Total Files Analyzed: {len(file_names)}
Analysis Generated: {datetime.now().strftime('%m/%d/%Y, %I:%M:%S %p')}

DOCUMENTS PROCESSED:
{chr(10).join(f'- {name}' for name in file_names)}

TEXT EXTRACTION SUMMARY:
- Successfully extracted text from {len(file_names)} documents
- Total characters processed: {total_chars}

AI ANALYSIS RESULTS:
{ai_analysis}

---
Report generated using Deepseek R1 via OpenRouter
""",
        "files_processed": file_names,
        "characters_processed": total_chars,
        "timestamp": datetime.now().isoformat()
    }
    
    return report

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze_documents():
    try:
        if 'files' not in request.files:
            return jsonify({'error': 'No files uploaded'}), 400
        
        files = request.files.getlist('files')
        if not files or all(file.filename == '' for file in files):
            return jsonify({'error': 'No files selected'}), 400
        
        extracted_texts = {}
        file_names = []
        
        # Extract text from all uploaded files
        for file in files:
            if file and file.filename.endswith('.pdf'):
                text = extract_text_from_pdf(file)
                if text:
                    extracted_texts[file.filename] = text
                    file_names.append(file.filename)
                else:
                    return jsonify({'error': f'Failed to extract text from {file.filename}'}), 400
        
        if not extracted_texts:
            return jsonify({'error': 'No valid text extracted from uploaded files'}), 400
        
        # Combine all extracted text for analysis
        combined_text = "\n\n".join([f"--- {name} ---\n{text}" for name, text in extracted_texts.items()])
        
        # Try AI analysis first
        print("Attempting AI analysis with Deepseek R1...")
        ai_analysis = analyze_financial_data_with_deepseek(combined_text)
        
        if ai_analysis:
            report = generate_full_report(ai_analysis, extracted_texts, file_names)
        else:
            print("AI analysis failed, generating fallback report")
            report = generate_fallback_report(extracted_texts, file_names)
        
        return jsonify(report)
        
    except Exception as e:
        print(f"Error in analyze_documents: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/health')
def health_check():
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
