build an n8n workflow to automate the below tasks without user input, no waiting, no halt, no exceptions.

### 🔴 Non-Revocable Execution Rules (Zero Exception)
1. **The "One-At-A-Time" Guardrail:** You are strictly prohibited from bundling or parsing multiple repositories concurrently. Process exactly ONE repository per turn. You must complete the discovery, mapping, and workspace cleanup for the active repo before touching the next one.
2. **Zero-Stub Standard:** All generated architectural documentation, plans, or adaptive code modules must be 100% complete. Do not produce code shortcuts, placeholders (`// implement later`), or empty stubs.

Tasks:
   I. analyse the 421 github repositories one-by-one
   II. execute a zero-exception, recursive, deep-dive architectural analysis of our target GitHub repositories one at a time

	### Step-by-Step Discovery Pipeline (To run in a loop per repo)

	#### Step 1: Clone & Structural Mapping (Wide Sweep)
		- Clone ONLY the current repository from the queue into a temporary directory `/tmp/workspace/active_target`.
		- Run an exhaustive map of the directory topology, configurations, manifests, and file hierarchies using local workspace tools.
		- Identify the project's programming languages, frameworks, and system dependencies.

	#### Step 2: Algorithmic & Quantitative Discovery (Deep Dive)
		Systematically scan the file contents of the codebase to isolate and categorize what functions exist. Group your findings into three distinct operational domains:
			1. **Data Engines:** Streaming candle parsers, data structures, historical file ingestors, or memory optimizations.
			2. **Signal & Execution Logic:** Alpha criteria, indicator code, machine learning feature engineering (e.g., XGBoost matrices), or mathematical formulas.
			3. **Risk Engineering:** Position-sizing code, circuit breakers, execution slicing, or protective guardrails.

	#### Step 3: Steelman Critique & Adaptation Blueprint
		- Evaluate the discovered logic against our current Python/Rust/MQL5 infrastructure.
		- Note any core processing bottlenecks (heavy Python iteration loops) that should be translated into multithreaded native Rust components wrapped via PyO3.
		- Output a comprehensive Markdown blueprint detailing the newly discovered features and how they fit into our modular microkernel architecture.

	#### Step 4: Ledger Persistence & Halt Checkpoint
		- Maintain a local file named `ingestion_blueprint.md`. Append the full structural and feature map of the repository to this ledger.
		- Completely purge and wipe `/tmp/workspace/active_target` to clean up the workspace environment.
		- Stop execution entirely. Print your full discovery report to the screen and ask me: **"Discovery complete for Repo [Name]. Ready to proceed to Repo [Next Name]?"** Wait for my manual text verification before advancing the queue.

	#### Step 5: Project Analysis and Mitigation
		- analyse the project, deep dive-in, drilldown, teardown, decompose, distill, dig deep like devils advocate
		- give me the best mitigation and your best of the best suggestions and solutions for all problems
		- prepare a todo tasks list, include all your suggestions and mitigations and implement everything.
		- update the todo tasks list as you go

   III. integrate all good and useful features and utilities of each repository
   IV. primary goal is discovery, classification, mapping and integration of features, functions, modules into eqats project in the github.com/sparlit/eqats repository
   V. do not wait for user input on completion of any task to proceed to next
   VI. no exceptions

### The Target Repositories Queue
   001. 0b01/tectonicdb
   002. 0xNoSystem/hyperliquid_rust_bot
   003. 0xramm/Indian-Stock-Market-API
   004. 0xRustPro/Stealth-BSC-BNB-create-devbuy-volume-bundler-trading-bot
   005. 0xTan1319/hyperliquid-trading-bot-rust
   006. 85599/BankNIFTY-Golden-Ratio-Strategy
   007. aadityatamrakar/option_chain_analysis
   008. aaryansinha16/AI-trader
   009. abhiwalia15/AI-for-Finance-Stocks-real-time-analysis-
   010. abuhurairalakdawala/indian-share-market
   011. adavarski/DevSecOps-full-integration-chain
   012. adityazerodha/holiday-calendar.github.io
   013. aeron7/nsepython
   014. aeron7/nsepythonserver
   015. affaan-m/dprc-autotrader-v2
   016. agrawalarnav129-ui/jarvis-trading
   017. AI4Finance-Foundation/FinRL-Trading
   018. ajakaiye33/ngrcoydisclosures
   019. ajeeshworkspace/indian-trading-skills
   020. akashnag/scripwatch
   021. akashyadavv/AlgoTradingNSE
   022. akshaypawar7/WODS
   023. akshayraje/get-nse-bhavcopy
   024. akshayz14/indian-stock-tracker
   025. akt114/BuyNSell
   026. AlexWan/OsEngine
   027. algotrading-lab/ai-algotrading-agent
   028. alloc7260/NSE
   029. alphabench/raptorbt
   030. althk/zerobha
   031. Ameobea/tickgrinder
   032. amitashwinibhagat/nse-swing-scanner
   033. amv-dev/yata
   034. Aneesh540/VSE
   035. Animesh4002/ai-stock-screener
   036. aniruddhsujish/NSETradeAgents
   037. anjulgarg/sharewatch
   038. ankitchaudhary6886/nse-system
   039. ankitsny/nse_scrapper
   040. anshulk/nse
   041. anshuthopsee/nse-oi-visualizer
   042. anthdm/rust-trading-engine
   043. anurag-roy/kite-option-chain
   044. anurag-roy/shoonya-option-chain
   045. api-evangelist/nse-india
   046. Aravin/Algo-Trade
   047. Aravin/nse-data
   048. ArishHassan/nse-live_testing
   049. arvchahal/kalshi-rs
   050. asavinov/intelligent-trading-bot
   051. AshayK003/nse-sentiment-analyzer
   052. ashgen/NSEDataAnalytics
   053. ashishkumar30/Stock_Market_Live_Trading_using_AI
   054. ashok-kollipara/options-oi
   055. AshokKumar3502/nse-quant-trading
   056. Ashutosh0x/rust-finance
   057. ashwanthkumar/Live-NSE-Stock
   058. athreysethumadhavan-finance/nse-var-dashboard
   059. atilaahmettaner/tradingview-mcp
   060. atrybyme/Open-Interest-NSE-Live-Analysis
   061. Atul-Anand-Jha/Time-Series-Forecast-NSEPy
   062. augmentalphawealth/Sectoral-Breadth-Dashboard
   063. avhz/RustQuant
   064. avin1311/nse-bse-dashboard
   065. avirichie/NSE-Closing-Stock-Price-Prediction-Using-LSTM
   066. ayushmaanbhav/StockMart
   067. Azhagesan-dev/OrderFlowMap
   068. BarathGB007/nse-options-data-collector
   069. BarathGB007/upstox-python-data
   070. barter-rs/barter-rs
   071. beinghorizontal/BhavFnO
   072. benimward9621/advanced-nse-momentum-terminal
   073. BennyThadikaran/eod2
   074. BennyThadikaran/eod2_data
   075. BennyThadikaran/NseIndiaApi
   076. Bhala-Srinivash/nse-trading-skills
   077. Bhumi008007/Stock_Prediction
   078. bitbytelabio/tradingview-rs
   079. blitzarx1/netstrat
   080. Bohr1005/xcrypto
   081. braverock/nse
   082. bshada/nse-bse-api
   083. bshada/nse-bse-mcp
   084. buzzsubash/algo_trading_strategies_india
   085. c3point/in-stock-screener
   086. c3point/Nse-Support-Tools
   087. calumrussell/rotala
   088. ccxt/ccxt
   089. chaitanyarahalkar/Financial-Info-Extractor
   090. chartiny/nse-daily-volatility-reports
   091. chauhanramkeval-blip/Nse-stock-bulk-deals-
   092. chauhanramkeval-blip/NSE-stock-market-bulk-deals-
   093. chinmayHundekari/NSEDatabase
   094. chinthan-11/NSE-BSE-Arbitrage-bot
   095. Chulilee/InterChangableTrade-Protocol
   096. Clayborninconsistent906/Indian-Stock-Market-API
   097. codegallivant/NSE-OHLC-scraper-plotter
   098. ConteurShadow/Polymarket-Trading-Bot-Rust
   099. crazygirl437/hyper-grid
   100. crypto-crawler/coinsignal
   101. cutupdev/Solana-Copytrading-bot
   102. cyberomin/NSEFinance-Python
   103. d-e-s-o/apcacli
   104. dallyshalla/tropix
   105. day0market/geger
   106. daydy-dev/moon-dev-ai-agents-for-trading
   107. debaonline4u/NSE-Data
   108. Debopam-D/Project-NIFTY
   109. deepentropy/ibx
   110. Degenapetrader/EVPOLY
   111. DegenSugarBoo/OpenBook
   112. deshpanda/nse-screener
   113. deshpanda/nse-screener-data
   114. deshwalmahesh/NSE-Stock-Scanner
   115. devAgam/chartink-to-tradingview-extension
   116. devangmukherjee/top-gainers-and-losers-nse
   117. devanshx9x/portfolio-monte-carlo
   118. dhruvan246/stocks-dashboard
   119. dkraj0612/nse-delivery-data
   120. dpeachpeach/kalshi-rust
   121. edison7009/EchoBird
   122. edtechre/pybroker
   123. eggmasonvalue/MTFDB
   124. ej9909-create/nse_52wk_screener
   125. ekanshsinghal/indian-stock-market
   126. Erio-Harrison/rust-trade
   127. featherenvy/botvana
   128. feroz-ghub-26/nse-sharia-news-feed
   129. feroze/YFinance-stock-history
   130. ferozmd53/nse-preopen-data
   131. ferrumfix/ferrumfix
   132. finstacklabs/finstack-mcp
   133. fluidex/dingir-exchange
   134. gabriel-milan/btrader
   135. gadiyar/NSEBhavcopy
   136. ganeshbiyer/Nse_Historical_Data
   137. georgiag7652/kronos-india
   138. get10101/10101
   139. ghostjat/Shoonya-php
   140. girishg4t/bhavCopy-downloader
   141. girishg4t/nse-bse-bhavcopy
   142. GirishKumarDV/Live-NSE-BSE-MCP
   143. gomitechnology-source/NSEBANK_HFT
   144. groverjikaladka/nse-bse-news-scanner
   145. gurudayal37/nse-data-syncer
   146. HarrierOnChain/Prediction-Markets-Trading-Bot-Toolkits
   147. HarshaDannina/Statistical-Arbitrage-Model
   148. Hash-It-Out/StockChain
   149. HawkEyeCoding/nse-oi-analysis
   150. hemangjoshi37a/TrendMaster
   151. hemenkapadia/getbhavcopy
   152. henry-richard7/NSE-Tool-Stocks-Aerial-View
   153. hermanodecastro/arbitrage-trading
   154. hgsujay/NseData
   155. hi-imcodeman/stock-nse-india
   156. HimanshuMohanty-Git24/RakshaQuant
   157. hirawatt/BSE_NSE_Announcement
   158. HmERro3/indian-trading-skills
   159. hopit-ai/india-trade-cli
   160. hotessy/nse-historical-data
   161. huseinzol05/Stock-Prediction-Models
   162. hyphenOs/tickdownload
   163. IBM/nse-observer
   164. imanojkumar/NSE-India-All-Stocks-Tickers-Data
   165. indianfoods-automation/nse
   166. Indra5196/NseStockAnalyser
   167. infinitefield/hypersdk
   168. inv2004/coinbase-pro-rs
   169. Ishaan3H/india-sector-screener
   170. Itsnrk1/nse-scanner
   171. jandginvestment/cci20-sma20-strategy
   172. JayeshSRathod/nse-scanner
   173. jensnesten/rust_bt
   174. jerryshell/midas
   175. jinit24/NSEDownload
   176. joaquinbejar/OptionStratLib
   177. johnebe2020-trade/Nse-scanner
   178. joshiadvait8/nse-data
   179. jugaad-py/master-data
   180. Julien-R44/cli-candlestick-chart
   181. JunbeomL22/trusted
   182. KalyanM45/MarketInsight
   183. kalyanroyinfo/stock-research-assistant
   184. Karthik002002/Stoklore
   185. kbizme/nsemine
   186. KenMwaura1/nse-stock-scraper
   187. khakhasshi/OptionWorkstation
   188. kishanlalchoudhary/NSE-Option-Chain
   189. kislayykumar/DailyVaultRates
   190. kkirankumar1511/nse-momentum-dashboard
   191. kondaiahpola1-wq/NSE-BSE-Event-Driven-Quant-Research-Platform
   192. kostorub/backtest
   193. krakenfx/kraken-cli
   194. kuldeeepy/algo-trader
   195. kwoshvick/NSE-Stock-Price-Crawler
   196. kwoshvick/NSE-Stock-Price-Prediction
   197. kwoshvick/NSE_Sentiment_Analysis
   198. lakshaysinghal/bhavCopy
   199. laminar-protocol/laminar-chain
   200. lavakus/nse-intraday-bot
   201. lebedov/nseindia_lob
   202. lebedov/nseindia_reformat
   203. llc-993/matching-core
   204. longbridge/longbridge-terminal
   205. Lqz13Th/extrema_infra
   206. maanavshah/stock-market-india
   207. maheshcharig/financial-data
   208. mailbagrahul/NSEoptionAlpha
   209. manavgupta83/nse-factor-engine
   210. mandarl/nsedata
   211. manddar/Open-Interest-Data-Extractor
   212. manishkr1754/NIFTY50_Data_Analysis_NSETOOLS_NSEPY_Python
   213. manishn32/option_chain_analyzer
   214. manitgupta/NSE-MCP
   215. mapsx/nse
   216. marketcalls/openalgo
   217. marketcalls/openchart
   218. marketcalls/sector-rotation-map
   219. MathisWellmann/lfest-rs
   220. MathisWellmann/trade_aggregation-rs
   221. maverick14303/stock-news-monitor
   222. MCHSL/tastytrade-rs
   223. me-imfhd/velocity
   224. meanalgo/meanalgo.github.io
   225. mechvec-debug/Ai_Driven_Algorithmic_trading
   226. Meetnepali/market-platform
   227. MelogneStudio/AlgoMLN
   228. meticulousCraftman/TickerStore
   229. mileswangs/pm-hftbacktest
   230. mineralres/rust-share
   231. mkshibu2/breadth-radar
   232. mlfreerl/pynse
   233. monomadic/rust-trailer
   234. mortdeus/solana-copy-sniper-mev-trading-bot
   235. mrappipramod/NSE-Data-Analysis
   236. mrimahajan/NSE-Market-App
   237. mrinaljhunjhunwala-ui/nse-smart-investor
   238. muepsilon/nsemodule
   239. MuokaPWambua/NSE-BOT
   240. muthuvenki/Stock
   241. mutxri/MUTXRI-TERMINAL
   242. nabrahma/ShortCircuit
   243. NagarajuGunda/NSEIndexOptionsData
   244. nash-io/openlimits
   245. nautechsystems/nautilus_trader
   246. nawin383/nse-top500-realtime-screener
   247. NayakwadiS/mftool
   248. NayakwadiS/NSE-Neuron
   249. neha01/Automate-Scrap-Nse-Data
   250. neilghosh/nse-historical-data
   251. NethermindEth/hummingboss
   252. ngm9/nsei_mcp_server
   253. nickmccullum/algorithmic-trading-python
   254. ninja-quant/ninjabook
   255. nirholas/pump-fun-sdk
   256. Nitin-Bhawarkar/NSE_Livedata_from_excel_extraction
   257. nived15/NSE-Stock-Fetcher
   258. nkaz001/hftbacktest
   259. NSEDownload/NSEDownload
   260. nvegupta1/SecurityWiseNSEData
   261. omerhalid/trading_engine_rust
   262. opmashin/nse_eod
   263. oscmcompany/fund
   264. P0W/nse_indices
   265. parmar-m/NSE_TRADER
   266. parthsamani/NSEstockF-OAlert
   267. patrick-weiss/PortfolioSorts_NSE
   268. Paul-Folbrecht/algo-trading
   269. pawan941394/Nse-Option-Chain---LLM-Project
   270. PEC-CSS/Stock-Watchlist
   271. perunnial/tickertrackbot
   272. pishangujeniya/kite-helper
   273. pishangujeniya/nse-stocks-data-scrapper
   274. pkjmesra/nseta
   275. pkjmesra/PKNSETools
   276. pkjmesra/PKScreener
   277. pmjangid90/StockMarket_Project
   278. pparesh25/NSE_BSE_Downloader
   279. pradeepjindal/nse-ml-2021
   280. pradyumnac/Excel-Tools-Indian-Stock-Market
   281. pramakrishn/express-option-chain
   282. pranjal-joshi/Screeni-py
   283. Prasad1612/NseKit-MCP
   284. Praveen-Mannem/nse-scanner
   285. pujanm/StockX
   286. purefinance/mmb
   287. QuantConnect/Lean.DataSource.Zerodha
   288. QuantMechanics/nse-premarket-data
   289. quantxaashish/nse-alpha
   290. Rachnog/Deep-Trading
   291. rahlumin/nseeod
   292. Rahulghuge94/trading_expiry
   293. rajaramsrinivas/GetNSEStockPrice
   294. rajeshkolhe110/nse-clock-data
   295. RajeshSivadasan/alice-blue-futures
   296. RajeshSivadasan/alice-blue-options-buying
   297. rajmaurya0904/bhav
   298. ramamet/nse1minR
   299. ranaroussi/qtpylib
   300. ratan00/nse-rs
   301. ratnaker16-bit/BrG-Zone-Scanner
   302. rbhatia46/Option-Writing-Calls-Using-Open-Interest
   303. reborn-digitech/swadeshi-tracker
   304. rehanhaider/stocky
   305. rhnvrm/stock-market-circulars
   306. ricequant/rqalpha
   307. rishikesh5/Algo-Trading-with-python
   308. RishilBhutada/rscreener
   309. riyaz-ali/bhav-copy
   310. rizwandil6/nse-whatsapp-alerts
   311. rjganatra/nse_analyser
   312. Rockbandassembly371/market-sentiments
   313. ROMESH1980/india-market-dashboard
   314. Ronak-59/Stock-Prediction
   315. rooneyrulz/agentic-stock-research-system
   316. rsh-lab/nse-stock-dashboard
   317. rsireddy002/nse-delivery-scanner
   318. rsquaredacademy/nse2r
   319. rthennan/ZerodhaWebsocket
   320. RuchiTanmay/nselib
   321. ruijiang81/AI_NSE
   322. RupeezyTech/algo_ai_skill
   323. ryqdev/golden
   324. s-agawane/stock-price-forecaster-lstm
   325. saber-hq/stable-swap
   326. sagar-n/autoresearch-nse
   327. sahilgupta/hakija
   328. sajal101agrawal/nse-options-last-5-years
   329. Sampad-Hegde/NSE-India-Web-Scraping
   330. sandeep-jaiswar/financeindia
   331. Sangram2905/NSE_Option_Chain
   332. Sangram2905/NSE_Option_Stock_market
   333. SankarGaneshb/Market-Rover
   334. sapare542/new_fyers_nse
   335. saubhagyapandey27/market-data-ops-platform
   336. ShabbirHasan1/fund-forge
   337. ShabbirHasan1/NSE-Data
   338. ShabbirHasan1/nsebsemcx
   339. ShahAnuj2610/QuickNSEDataFetcher
   340. shamu0509/nse-bse-mcp
   341. shikharka/stocks-app
   342. ShrewdLemon/shunkan
   343. ShreyashDarade/AI_Trading_Calls_Pridictor
   344. Shubxam/Nifty-500-Live-Sentiment-Analysis
   345. SiddharthaKrSaha/nse-screener
   346. singhsurendrapratap/nse-swing-screener
   347. skharchikov/polymarket-bot
   348. sleeyax/ml-crypto-trading-bot
   349. SnowCheetos/AutoMoonBot
   350. sonimaharshi1999/JyotishTrader
   351. Stellar-xcrow/StellarEscrow
   352. stevschmid/nsearch
   353. stockalgo/bandl
   354. studiogangster/next-gen-algo-trading-bot
   355. studiogangster/sensibull-realtime-options-api-ingestor
   356. subaquatic-pierre/raderbot
   357. sudhanshusingh23-wiz/nse-momentum-data
   358. sumitjoshi21/NSE-Real-Time-Stocks-Analysis-and-Predictions-Using-P
   359. sumitsainidev/OIAnalysis
   360. sumukshashidhar-archive/nse-data
   361. Superalgos/Algorithmic-Trading-Plugins
   362. Superalgos/Trading-Signals-Plugins
   363. svsashank/NSE_1000Cr_Momentum
   364. swapniljariwala/nsepy
   365. swapniljariwala/quotelib
   366. Tapetide-hq/nse-bse-indian-stock-market-data-mcp
   367. tcharding/rust-crypto-trader
   368. TechfaneTechnologies/nseproxy
   369. TechfaneTechnologies/pytvlwcharts
   370. techyaura/nse-bhavcopy
   371. telepair/polymarket-hft
   372. tesserspace/tesser
   373. TheHardeep/fenix
   374. Thejesh-k463/VYUHA-LOG
   375. theonlyanil/pnsea
   376. thiyagab/autotrade
   377. tilak999/NSE-Data-bank
   378. TopTrenDev/polymarket-kalshi-arbitrage-bot
   379. ttzztztz/rabbit_trading
   380. turtlehq-tech/turtlestack-lite
   381. uashogeschoolutrecht/NSE_Analyses
   382. VarunDivakar/NSEpy-Continuous-data
   383. VarunS2002/Python-NSE-Option-Chain-Analyzer
   384. Vedl/nse-equity-research-report-generator
   385. ven2day/opendelta-nse
   386. viabtc/viabtc_exchange_server
   387. vignesh-moorthy/NSE-DayData
   388. vikaschouhan/portfolio_analysis
   389. Vikranth3140/NSE-BSE-Stock-Prices-Automation
   390. vinay-ram1999/AlgoTrade-API
   391. vinodscode/ipo-exchange-scrape
   392. vinothkumarmuruga-cyber/NSE-PRE-MARKET
   393. vivektmurali/obscura-intel
   394. vividvilla/NSE-Live-Market
   395. vjpaij/ladder
   396. voicegn/polymarket-bot
   397. volatility4u/nsepython
   398. vsjha18/nsecli
   399. vsjha18/nsetools
   400. wangrunji0408/most
   401. waxdred/Binance-Trader-Bot
   402. webclinic017/Tradingview-Screenshot-Bot-
   403. white-trade-loan/algo-trading-platform
   404. WizardRao/Rao-s-SCRAP-Platform
   405. WooKiao/Crypto-trading-Hunter
   406. x86y/dynasty
   407. xorasysgen/Nse-OI-Scanner
   408. yongkangc/lighter-rust
   409. yswa-var/RRG
   410. yusuf4030/the-data-analyst-toolkit
   411. yutiansut/qaaccount-rs
