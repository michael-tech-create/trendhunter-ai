TrendHunter backend is up. Live demo confirmed the core story: agent can want the trade; risk gate still blocks it.                              
                                                                                                                                                  
 What's built                                                                                                                                     
                                                                                                                                                  
 ```                                                                                                                                              
   backend/                                                                                                                                       
   ├── main.py              # FastAPI + WebSocket (/scan, /trades, /portfolio, /ws)                                                               
   ├── pipeline.py          # Full 5-layer orchestration                                                                                          
   ├── config.py            # Settings + risk defaults                                                                                            
   ├── signals.py           # RSI, momentum, volume, HV                                                                                           
   ├── technical.py         # Support levels + strike targeting                                                                                   
   ├── options.py           # Chain fetch (CLI → yfinance fallback), IV rank, CSP pick                                                            
   ├── cli_wrapper.py       # Alpaca CLI + retries                                                                                                
   ├── agent.py             # Gemini + skeptical heuristic fallback                                                                               
   ├── earnings.py          # Earnings blackout input                                                                                             
   ├── risk_engine.py       # Hard RiskGate (no AI override)                                                                                      
   ├── trade_autopsy.py     # Structured explainability                                                                                           
   ├── execution.py         # CSP paper orders (dry-run when CLI missing)                                                                         
   ├── pnl.py               # Portfolio snapshot                                                                                                  
   ├── demo.py              # Fast CLI demo                                                                                                       
   ├── db/models.py + schema.py                                                                                                                   
   └── tests/               # 16 passing                                                                                                          
 ```                                                                                                                                              
                                                                                                                                                  
 Verified behavior                                                                                                                                
                                                                                                                                                  
 - 16/16 tests pass                                                                                                                               
 - Live demo.py AAPL: heuristic said SELL_PUT → gate rejected (premium_ratio + capital) → autopsy recorded both sides, no order                   
 - Same pattern on F (capital OK, skinny premium still blocked)                                                                                   
                                                                                                                                                  
 That matches the thesis: premium alone never forces a trade.                                                                                     
                                                                                                                                                  
 Run it                                                                                                                                           
                                                                                                                                                  
 ```bash                                                                                                                                          
   cd backend                                                                                                                                     
   source .venv/bin/activate                                                                                                                      
                                                                                                                                                  
   python demo.py AAPL F          # offline-friendly (heuristic, dry-run)                                                                         
   uvicorn main:app --reload --port 8000                                                                                                          
   # POST /scan   WS /ws   GET /trades   GET /portfolio                                                                                           
 ```                                                                                                                                              
                                                                                                                                                  
 Copy backend/.env.example → .env and set GEMINI_API_KEY when ready. Install/auth Alpaca CLI to leave dry-run.                                    
                                                                                                                                                  
 Sensible next steps                                                                                                                              
                                                                                                                                                  
 1. Wire real Gemini tool-calling (not just JSON completion)                                                                                      
 2. Install Alpaca CLI and flip dry_run_orders=False                                                                                              
 3. Tune watchlist / capital limits for names that can clear 0.125 in paper                                                                       
 4. React dashboard against /ws                                                                                                                   
                                                                                                                                                  
 Want me to tackle any of those next?                                                                                                             
