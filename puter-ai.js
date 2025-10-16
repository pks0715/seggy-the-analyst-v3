// puter-ai.js - Puter.js AI integration for Seggy Analyst

class PuterAIClient {
    constructor() {
        this.isInitialized = false;
        this.initialize();
    }

    initialize() {
        if (typeof puter !== 'undefined') {
            this.isInitialized = true;
            console.log("✓ Puter.js initialized successfully");
        } else {
            console.error("✗ Puter.js not loaded");
        }
    }

    async analyzeBatch(batchContent, batchNum, totalBatches, ddType, reportFocus) {
        if (!this.isInitialized) {
            throw new Error("Puter.js not initialized");
        }

        const prompt = this.createBatchPrompt(batchContent, batchNum, totalBatches, ddType, reportFocus);
        
        try {
            const response = await puter.ai.chat(prompt, {
                model: "gpt-4o",  // Using GPT-4o for good balance of speed and quality
                temperature: 0.1,
                max_tokens: 4000
            });
            
            return this.validateResponse(response);
        } catch (error) {
            console.error(`Batch ${batchNum} analysis failed:`, error);
            throw error;
        }
    }

    async synthesizeReports(batchReportsContent, ddType, reportFocus, checklistType, totalFiles) {
        if (!this.isInitialized) {
            throw new Error("Puter.js not initialized");
        }

        const prompt = this.createSynthesisPrompt(batchReportsContent, ddType, reportFocus, checklistType, totalFiles);
        
        try {
            const response = await puter.ai.chat(prompt, {
                model: "gpt-4o",
                temperature: 0.1,
                max_tokens: 6000
            });
            
            return this.validateResponse(response);
        } catch (error) {
            console.error("Synthesis failed:", error);
            throw error;
        }
    }

    createBatchPrompt(batchContent, batchNum, totalBatches, ddType, reportFocus) {
        let filesContent = "";
        batchContent.forEach(doc => {
            filesContent += `\n${'='.repeat(60)}\nFILE: ${doc.filename}\n${'='.repeat(60)}\n`;
            filesContent += doc.content.substring(0, 12000);
            filesContent += "\n\n";
        });

        return `ANALYZE THESE FINANCIAL DOCUMENTS FOR M&A DUE DILIGENCE (BATCH ${batchNum}/${totalBatches}):

DOCUMENTS PROVIDED:
${filesContent}

EXTRACT AND ANALYZE ACTUAL FINANCIAL DATA:

REVENUE & GROWTH:
- What specific revenue numbers are mentioned? Include amounts, dates, and periods.
- Calculate growth rates between periods using actual numbers.
- Identify revenue trends and patterns.

PROFITABILITY:
- What profit margins are stated? (gross, operating, net, EBITDA)
- Extract actual percentages and amounts.
- Analyze cost structure and major expenses.

BALANCE SHEET:
- What asset amounts are listed? (current assets, fixed assets, total assets)
- What liability amounts are listed? (current liabilities, long-term debt, total liabilities)
- Calculate key ratios: current ratio, debt-to-equity.

CASH FLOW:
- What cash flow numbers are present? (operating, investing, financing)
- Analyze cash position and liquidity.

KEY FINDINGS:
List 5-7 specific findings with:
- The actual data point or figure
- Which document it came from  
- Why it matters for due diligence

RISKS IDENTIFIED:
List 3-5 specific risks found in these documents with:
- Description tied to actual data
- Severity assessment
- Source document

DATA QUALITY ASSESSMENT:
- What financial information is complete?
- What key data is missing?
- Any inconsistencies between documents?

IMPORTANT: 
- Use ONLY numbers and facts from the documents above.
- If data is not found, state "Not specified in documents".
- Reference specific documents for each data point.
- Be specific and data-driven in your analysis.`;
    }

    createSynthesisPrompt(batchReportsContent, ddType, reportFocus, checklistType, totalFiles) {
        return `CREATE A COMPREHENSIVE M&A DUE DILIGENCE REPORT:

BATCH ANALYSIS RESULTS:
${batchReportsContent}

CREATE A PROFESSIONAL EXECUTIVE REPORT:

# EXECUTIVE SUMMARY
[3 paragraphs summarizing overall financial health, key value drivers, and preliminary recommendation based on ACTUAL data]

## Financial Performance Summary
- Revenue Analysis: [Specific numbers, growth rates, trends]
- Profitability: [Actual margins, profit trends]  
- Cash Flow & Liquidity: [Cash position, flow analysis]
- Balance Sheet Strength: [Asset quality, debt levels, ratios]

## Key Financial Metrics
[List 8-10 most important metrics with ACTUAL numbers and sources]

## Comprehensive Risk Assessment
[8-12 specific risks with severity, financial impact, and mitigation suggestions]

## Operational Analysis
[Business model, customer concentration, supplier dependencies based on actual data]

## Valuation Considerations
[Value drivers, quality of earnings, comparable analysis]

## Final Recommendation
[Clear Go/No-Go/Conditional Go with data-driven rationale]

## Required Additional Diligence
[Specific items needing further investigation]

CRITICAL: 
- Use ONLY the actual data from the batch reports above
- Never use placeholders or templates
- All analysis must be grounded in specific numbers found
- Reference which batches/documents provided key data
- Be specific, actionable, and professional`;
    }

    validateResponse(response) {
        if (!response || typeof response !== 'string') {
            throw new Error("Invalid response from AI");
        }

        // Check for template responses
        const templatePhrases = [
            "you'll need to", "placeholder", "template", "framework", 
            "breakdown of how", "incorporating the specific", "this is a great"
        ];
        
        const hasTemplate = templatePhrases.some(phrase => 
            response.toLowerCase().includes(phrase)
        );

        if (hasTemplate) {
            throw new Error("AI returned template response instead of actual analysis");
        }

        return response;
    }
}

// Create global instance
window.puterAIClient = new PuterAIClient();
