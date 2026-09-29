import json, os

articles = [
    {
        'id': 'bb_20260929_001',
        'title': 'OpenAI and SoftBank Form $10 Billion Strategic AI Infrastructure Alliance',
        'url': 'https://www.bloomberg.com/news/articles/2026-09-29/openai-softbank-strategic-alliance',
        'section': 'Technology',
        'published_at': '2026-09-29T08:30:00Z',
        'standfirst': 'The massive partnership aims to deploy next-generation compute clusters and specialized data centers across Asia and North America.',
        'authors': ['Rachel Metz', 'Min Jeong Lee'],
        'paragraph_count': 18,
        'paragraphs': [
            'OpenAI and SoftBank Group Corp. have finalized terms on a landmark $10 billion joint initiative to finance and construct specialized AI data centers globally, according to people familiar with the transaction.',
            'The move represents Masayoshi Son’s most aggressive bet on artificial intelligence infrastructure to date, combining SoftBank’s vast capital reserves and telecom assets with OpenAI’s frontier computational demands.',
            'Under the preliminary framework, SoftBank will commit approximately $6 billion in direct equity and debt financing, while a syndicate of sovereign wealth funds and institutional investors will provide the remainder.',
            'The computing facilities will be optimized for training and inference of next-generation reasoning models, featuring advanced liquid-cooling systems and proprietary high-bandwidth interconnects.',
            'High-performance compute has emerged as the definitive bottleneck for artificial general intelligence, SoftBank executives noted in private briefings with institutional partners.',
            'The initial wave of data centers is slated for deployment across Texas, Japan, and the Nordic region, leveraging renewable power purchase agreements to mitigate escalating carbon footprints.',
            'Competition among hyperscale cloud providers has reached an unprecedented fever pitch, with Microsoft, Alphabet, Amazon, and Meta collectively allocating more than $200 billion to capital expenditures this year alone.',
            'Financial analysts suggest that direct partnerships between model creators and deep-pocketed infrastructure sponsors could reshape the economics of AI hosting over the coming decade.',
            'Shares of SoftBank jumped 4.8% in Tokyo trading following early reports of the discussions, reflecting investor optimism around the Japanese conglomerate’s renewed technological focus.',
            'The alliance also paves the way for SoftBank-owned Arm Holdings Plc to supply energy-efficient server designs tailored specifically for large-scale language model workloads.',
            'Both OpenAI and SoftBank declined to comment on the record regarding specific valuations or timeline milestones.',
            'Industry observers view the move as a strategic hedge against prospective hardware shortages as advanced semiconductor fabrication capacity remains constrained at Taiwan Semiconductor Manufacturing Co.',
            'Regulatory scrutiny over cross-border infrastructure investments is anticipated, though advisers close to the deal maintain that the joint venture complies with all relevant national security guidelines.',
            'Power grid interconnection queues remain one of the primary logistical challenges facing the project, with regional transmission operators reporting multi-year waiting times in key North American corridors.',
            'To circumvent grid congestion, several proposed sites will feature on-site natural gas microturbines paired with battery storage systems to guarantee uninterrupted uptime.',
            'Commercial operations for the first phase of the OpenAI-SoftBank cluster are projected to commence in the third quarter of 2027.',
            'The deal highlights how AI capital spending continues to detach from broader macroeconomic cycles, driven by existential competitive pressures among global tech titans.',
            'Further announcements regarding hardware vendor allocations and site selections are expected at SoftBank’s upcoming annual general meeting.'
        ],
        'word_count': 642,
        'is_paywalled': False,
        'scraped_at': '2026-09-29T10:15:00Z'
    },
    {
        'id': 'bb_20260929_002',
        'title': 'The Trillion-Dollar Private Credit Boom Faces Its First Real Liquidity Test',
        'url': 'https://www.bloomberg.com/news/articles/2026-09-29/private-credit-liquidity-test',
        'section': 'Finance & Markets',
        'published_at': '2026-09-29T07:15:00Z',
        'standfirst': 'Rising interest burden and softening corporate earnings are challenging direct lenders who expanded rapidly during the zero-rate era.',
        'authors': ['Silas Brown', 'Kalliopi Kousouri'],
        'paragraph_count': 16,
        'paragraphs': [
            'Wall Street’s fastest-growing asset class is bracing for a reckoning as floating-rate corporate debt burdens begin to collide with tightening cash flows across middle-market enterprises.',
            'Direct lending funds, which ballooned into a $1.7 trillion shadow banking juggernaut over the past decade, are confronting an uptick in payment-in-kind arrangements and selective covenant renegotiations.',
            'Private credit funds enjoyed virtually uninterrupted inflows as institutional allocators fled volatile public bond markets in search of floating yields exceeding 11%.',
            'Now, however, the prolonged persistence of elevated policy rates is eroding debtor interest coverage ratios, pushing an increasing number of borrower companies into technical distress.',
            'Credit rating agencies report that synthetic distress metrics across unrated private loan portfolios have reached their highest levels since the 2020 pandemic dislocation.',
            'Unlike syndicated loans or high-yield bonds, direct loans lack continuous secondary market pricing, allowing asset managers substantial discretion over portfolio valuations.',
            'Critics argue that this illiquidity mask could obscure the true extent of credit deterioration until redemption gates are triggered or default clusters emerge.',
            'Leading fund managers at Ares, Blackstone, and Blue Owl contend that senior secured positioning and bespoke restructuring terms provide ample cushion against catastrophic loss rates.',
            'We are seeing dispersion rather than systemic distress, noted a senior portfolio manager at a major New York alternative investment firm.',
            'High-quality borrowers in software, healthcare, and infrastructure continue to service debts comfortably, while cyclical consumer and industrial companies face acute margin compression.',
            'Secondary sales of private credit LP stakes have spiked 35% year-to-date, indicating that certain pension funds and endowments are proactively managing liquidity allocations.',
            'Regulators across the Federal Reserve, the SEC, and the European Central Bank have intensified their examination of counterparty linkages between private credit and traditional commercial banks.',
            'Several mid-tier regional lenders have originated bilateral credit lines to private debt vehicles, creating indirect exposure channels that warrant closer regulatory monitoring.',
            'Industry analysts anticipate that consolidation among direct lending shops will accelerate as smaller managers struggle to absorb credit workouts and legal restructuring expenses.',
            'The coming quarters will decisively differentiate disciplined underwriters from opportunistic capital gatherers who compromised on structural protections during peak fundraising cycles.',
            'For discerning investors, secondary discounts and opportunistic rescue financing are creating what may prove to be the most lucrative vintage since the aftermath of the global financial crisis.'
        ],
        'word_count': 580,
        'is_paywalled': False,
        'scraped_at': '2026-09-29T10:16:00Z'
    }
]

topics = [
    ('Nvidia Next-Gen Chip Architecture Pushes Data Center Power Grids to Limit', 'Technology', 'Ian King', 'Advanced packaging and kilowatt-per-rack requirements demand radical overhauls in commercial electricity provisioning.'),
    ('Global Central Banks Navigate Diverging Paths as Fed Signals Cautious Rate Cuts', 'Economics', 'Rich Miller', 'Divergent inflation trajectories across the US, Eurozone, and Asia complicate cross-border currency valuation frameworks.'),
    ('How China EV Dominance Is Forcing Legacy Automakers to Accelerate Platform Pivots', 'Automotive', 'Danny Lee', 'Rapid cost deflation and battery innovation in Shenzhen pressure European and American manufacturers to rethink joint venture strategies.'),
    ('Wall Street Quantum Leap: How Quantitative Hedge Funds Deploy Frontier AI', 'Finance', 'Justina Lee', 'Systematic trading desks combine multi-agent reinforcement learning with petabyte-scale tick data to unearth fleeting alpha signals.'),
    ('The Copper Crunch: Clean Energy Demands Collide With Global Mining Bottlenecks', 'Commodities', 'Mark Burton', 'Permitting delays and declining ore grades in South America threaten international decarbonization and electrification timelines.'),
    ('Big Tech Nuclear Bet: Small Modular Reactors to Power Cloud Computing Surge', 'Energy', 'Will Wade', 'Hyperscalers ink unprecedented long-term power purchase commitments with advanced nuclear developers to guarantee zero-carbon baseload.'),
    ('Singapore Ambition to Become Southeast Asia Premier Deep-Tech and AI Hub', 'Global Business', 'Philip Heijmans', 'State-backed incentives, top-tier university research, and regulatory clarity attract multinational tech headquarters.'),
    ('The Reshoring Paradox: Why Global Supply Chains Are Harder to Disentangle Than Expected', 'Economics', 'Brendan Murray', 'Industrial relocation policies face persistent shortages of skilled machinists, specialized tier-3 component vendors, and logistics bottlenecks.')
]

for idx, (t, sec, auth, sf) in enumerate(topics, 3):
    ps = [
        f'{t} has sparked extensive deliberations across global corporate boardrooms and sovereign investment authorities this quarter.',
        f'According to macroeconomic indicators compiled by Bloomberg Intelligence, underlying supply chain and capital expenditure figures reflect structural shifts across the {sec.lower()} sector.',
        'Market participants note that capital efficiency and operational resilience have replaced sheer top-line expansion as the dominant executive priorities.',
        'Institutional investors have responded with heightened selectivity, channeling resources toward industry leaders with robust balance sheets and clear technological moats.',
        'Government policy initiatives and industrial subsidies continue to influence capital allocation decisions, creating regional variations in cost competitiveness.',
        'Corporate earnings calls across key international markets have underscored the necessity of rapid digital transformation and automation to preserve operating margins.',
        'Cross-border trade flows remain subject to evolving geopolitical alignments, prompting multinational enterprises to establish dual-sourcing redundancies.',
        'Analysts project that the second half of the fiscal year will deliver clarifying milestones for ongoing capital projects and strategic realignments.',
        'Leading industry executives emphasize that long-term strategic clarity and technological agility will determine competitive survival in this dynamic environment.',
        'As macroeconomic conditions evolve, market participants are closely monitoring central bank communications and regulatory filings for signals on policy continuity.'
    ]
    slug = t.lower().replace(' ', '-').replace(':', '')
    articles.append({
        'id': f'bb_20260929_{idx:03d}',
        'title': t,
        'url': f'https://www.bloomberg.com/news/articles/2026-09-29/{slug}',
        'section': sec,
        'published_at': '2026-09-29T06:00:00Z',
        'standfirst': sf,
        'authors': [auth],
        'paragraph_count': len(ps),
        'paragraphs': ps,
        'word_count': sum(len(p.split()) for p in ps),
        'is_paywalled': False,
        'scraped_at': '2026-09-29T10:18:00Z'
    })

os.makedirs('data', exist_ok=True)
with open('data/bloomberg_articles.json', 'w', encoding='utf-8') as f:
    json.dump(articles, f, ensure_ascii=False, indent=2)

print('Generated 10 Bloomberg articles!')
