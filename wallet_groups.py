"""
Wallet Grouping Feature
Groups wallets by their labels (e.g., "Trust Wallet BNB", "Trust Wallet ETH" → "Trust Wallet")
"""

import asyncio
import aiosqlite
import aiohttp
from typing import List, Dict, Tuple, Optional
from decimal import Decimal
import re
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
import io
from PIL import Image, ImageDraw, ImageFont

# ===================================================== 
# WALLET NAME DATABASE
# ===================================================== 
KNOWN_WALLET_NAMES = [
    # Popular wallets
    "Trust Wallet",
    "MetaMask",
    "Coinbase Wallet",
    "Ledger",
    "Trezor",
    "Exodus",
    "Phantom",
    "Rainbow",
    "SafePal",
    "Argent",
    "Zerion",
    "Rabby",
    
    # Exchange wallets
    "Binance",
    "Coinbase",
    "Kraken",
    "Kucoin",
    "Bybit",
    "OKX",
    "Huobi",
    "Gate.io",
    "Bitfinex",
    "Gemini",
    
    # Hardware wallets
    "Ledger Nano",
    "Trezor One",
    "Trezor Model T",
    "KeepKey",
    "BitBox",
    "CoolWallet",
    
    # Other categories
    "Main",
    "Trading",
    "Savings",
    "Cold Storage",
    "Hot Wallet",
    "DeFi",
    "NFT",
    "Gaming",
    "Staking",
    "Airdrop",
    "Personal",
    "Business",
    "Family",
    "Friends",
]

# Sort by length (longest first) for better matching
KNOWN_WALLET_NAMES.sort(key=len, reverse=True)

# ===================================================== 
# HELPER FUNCTIONS
# ===================================================== 

def extract_wallet_group(label: str) -> Optional[str]:
    """
    Extract wallet group name from label
    
    Examples:
    "Trust Wallet BNB" → "Trust Wallet"
    "MetaMask ETH Main" → "MetaMask"
    "Binance Trading" → "Binance"
    "My Main Wallet" → "Main"
    """
    label_lower = label.lower()
    
    # Check against known wallet names
    for wallet_name in KNOWN_WALLET_NAMES:
        if wallet_name.lower() in label_lower:
            return wallet_name
    
    # If no match, try to extract first word(s)
    # Look for patterns like "XXX Wallet", "XXX Exchange", etc.
    patterns = [
        r'^([A-Za-z0-9]+)\s+Wallet',
        r'^([A-Za-z0-9]+)\s+Exchange',
        r'^([A-Za-z0-9]+)\s+\w+$',  # Two words
    ]
    
    for pattern in patterns:
        match = re.match(pattern, label)
        if match:
            return match.group(1)
    
    return None

def group_wallets_by_name(wallets: List[Tuple]) -> Dict[str, List[Tuple]]:
    """
    Group wallets by extracted wallet name
    
    Returns:
    {
        "Trust Wallet": [(wallet1,), (wallet2,), ...],
        "MetaMask": [(wallet3,), ...],
        "_ungrouped": [(wallet4,), ...]  # Wallets that don't match any group
    }
    """
    groups = {}
    ungrouped = []
    
    for wallet in wallets:
        # wallet structure: (id, user_id, network, address, label, last_tx, created_at)
        label = wallet[4]
        group_name = extract_wallet_group(label)
        
        if group_name:
            if group_name not in groups:
                groups[group_name] = []
            groups[group_name].append(wallet)
        else:
            ungrouped.append(wallet)
    
    if ungrouped:
        groups["_ungrouped"] = ungrouped
    
    return groups

async def get_wallet_balance(address: str, network: str, 
                            etherscan_key: str, solscan_key: str,
                            session: aiohttp.ClientSession) -> Dict:
    """
    Get balance for a wallet
    Returns: {"native_amount": float, "usd_value": float, "token_symbol": str}
    """
    from decimal import Decimal
    
    # Import network registries (you'll need to import these from your main file)
    # For now, I'll create simplified versions
    
    try:
        if network == "ethereum" or network.startswith("ethereum_"):
            # EVM chains
            if not etherscan_key:
                return {"native_amount": 0, "usd_value": 0, "token_symbol": "ETH"}
            
            # Get chain_id (simplified - you'd import this from main)
            chain_id = 1  # Ethereum mainnet
            
            url = f"https://api.etherscan.io/v2/api?chainId={chain_id}&module=account&action=balance&address={address}&apikey={etherscan_key}"
            
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    js = await r.json()
                    if js.get("status") == "1":
                        balance = int(js["result"]) / 1e18
                        
                        # Get ETH price (simplified)
                        price = await get_simple_price("ETH", session)
                        
                        return {
                            "native_amount": balance,
                            "usd_value": balance * price,
                            "token_symbol": "ETH"
                        }
        
        elif network == "tron":
            url = f"https://apilist.tronscanapi.com/api/account?address={address}"
            
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    js = await r.json()
                    balance = js.get("balance", 0) / 1_000_000
                    
                    price = await get_simple_price("TRX", session)
                    
                    return {
                        "native_amount": balance,
                        "usd_value": balance * price,
                        "token_symbol": "TRX"
                    }
        
        elif network == "solana":
            if not solscan_key:
                return {"native_amount": 0, "usd_value": 0, "token_symbol": "SOL"}
            
            url = f"https://public-api.solscan.io/account/{address}"
            headers = {"token": solscan_key}
            
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    js = await r.json()
                    balance = js.get("lamports", 0) / 1e9
                    
                    price = await get_simple_price("SOL", session)
                    
                    return {
                        "native_amount": balance,
                        "usd_value": balance * price,
                        "token_symbol": "SOL"
                    }
    
    except Exception as e:
        print(f"Error fetching balance for {network}/{address}: {e}")
    
    return {"native_amount": 0, "usd_value": 0, "token_symbol": "?"}

async def get_simple_price(symbol: str, session: aiohttp.ClientSession) -> float:
    """Get simple USD price from CoinGecko"""
    coin_ids = {
        "ETH": "ethereum",
        "TRX": "tron",
        "SOL": "solana",
        "BNB": "binancecoin",
        "MATIC": "matic-network",
        "TON": "the-open-network",
    }
    
    coin_id = coin_ids.get(symbol.upper(), symbol.lower())
    
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"
        
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status == 200:
                js = await r.json()
                return js.get(coin_id, {}).get("usd", 0)
    except:
        pass
    
    return 0

def get_network_display(network: str) -> str:
    """Get display name for network"""
    display_names = {
        "ethereum": "Ethereum",
        "polygon": "Polygon",
        "arbitrum": "Arbitrum",
        "tron": "TRON",
        "solana": "Solana",
        "ton": "TON",
        "bnb": "BNB Chain",
    }
    
    return display_names.get(network, network.title())

# ===================================================== 
# IMAGE GENERATION
# ===================================================== 

async def generate_wallet_image(wallet_name: str, total_usd: float, 
                               holdings: List[Dict]) -> io.BytesIO:
    """
    Generate a visual card for the wallet group
    
    Args:
        wallet_name: Name of wallet group
        total_usd: Total USD value
        holdings: List of {"network": str, "amount": float, "symbol": str, "usd": float}
    """
    
    # Image dimensions
    width = 800
    base_height = 400
    item_height = 60
    height = base_height + (len(holdings) * item_height)
    
    # Create image with gradient background
    img = Image.new('RGB', (width, height), color='#1a1a2e')
    draw = ImageDraw.Draw(img)
    
    # Try to load a nice font, fallback to default
    try:
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
        subtitle_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)
        item_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
        small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
    except:
        title_font = ImageFont.load_default()
        subtitle_font = ImageFont.load_default()
        item_font = ImageFont.load_default()
        small_font = ImageFont.load_default()
    
    # Gradient background
    for i in range(height):
        r = int(26 + (i / height) * 20)
        g = int(26 + (i / height) * 30)
        b = int(46 + (i / height) * 40)
        draw.rectangle([(0, i), (width, i + 1)], fill=(r, g, b))
    
    # Header section
    draw.rectangle([(20, 20), (width - 20, 180)], fill='#16213e', outline='#0f3460', width=3)
    
    # Wallet name
    draw.text((40, 40), wallet_name, fill='#ffffff', font=title_font)
    
    # Total value
    total_text = f"${total_usd:,.2f}"
    draw.text((40, 100), "Total Value", fill='#94a3b8', font=small_font)
    draw.text((40, 125), total_text, fill='#4ade80', font=subtitle_font)
    
    # Holdings section
    y_offset = 220
    
    if holdings:
        draw.text((40, y_offset), "Holdings", fill='#94a3b8', font=small_font)
        y_offset += 40
        
        for holding in holdings:
            # Background for each item
            draw.rectangle(
                [(40, y_offset), (width - 40, y_offset + 50)],
                fill='#16213e',
                outline='#0f3460',
                width=2
            )
            
            # Network name
            network_text = holding['network']
            draw.text((60, y_offset + 5), network_text, fill='#e2e8f0', font=item_font)
            
            # Amount
            amount_text = f"{holding['amount']:.6f} {holding['symbol']}"
            draw.text((60, y_offset + 30), amount_text, fill='#94a3b8', font=small_font)
            
            # USD value (right aligned)
            usd_text = f"${holding['usd']:,.2f}"
            # Get text width for right alignment
            bbox = draw.textbbox((0, 0), usd_text, font=item_font)
            text_width = bbox[2] - bbox[0]
            draw.text((width - 60 - text_width, y_offset + 15), usd_text, fill='#4ade80', font=item_font)
            
            y_offset += 60
    else:
        draw.text((40, y_offset), "No holdings data", fill='#94a3b8', font=item_font)
    
    # Footer
    draw.text((40, height - 40), "CryptoAlert Monitor", fill='#64748b', font=small_font)
    
    # Save to BytesIO
    bio = io.BytesIO()
    bio.name = f'{wallet_name.replace(" ", "_")}.png'
    img.save(bio, 'PNG')
    bio.seek(0)
    
    return bio

# ===================================================== 
# ROUTER & HANDLERS
# ===================================================== 

router = Router()

@router.message(Command("wallet"))
async def cmd_wallet_groups(m: Message, db_path: str, etherscan_key: str, 
                            solscan_key: str, session: aiohttp.ClientSession):
    """
    Show wallet groups
    """
    user_id = m.from_user.id
    
    # Get user's wallets
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute("SELECT * FROM wallets WHERE user_id=?", (user_id,))
        wallets = await cur.fetchall()
    
    if not wallets:
        await m.answer(
            "📭 No wallets added yet.\n\n"
            "Use /addaddress to add wallets for monitoring.\n\n"
            "💡 **Tip:** Name your wallets like:\n"
            "• Trust Wallet BNB\n"
            "• Trust Wallet ETH\n"
            "• MetaMask Polygon\n\n"
            "The bot will automatically group them!"
        )
        return
    
    # Group wallets
    groups = group_wallets_by_name(wallets)
    
    # Build keyboard
    keyboard = []
    
    # Sort groups (ungrouped last)
    sorted_groups = sorted(
        [(k, v) for k, v in groups.items() if k != "_ungrouped"],
        key=lambda x: x[0]
    )
    
    if "_ungrouped" in groups:
        sorted_groups.append(("_ungrouped", groups["_ungrouped"]))
    
    for group_name, group_wallets in sorted_groups:
        if group_name == "_ungrouped":
            display_name = "🔹 Other Wallets"
        else:
            display_name = f"💼 {group_name}"
        
        count = len(group_wallets)
        
        keyboard.append([
            InlineKeyboardButton(
                text=f"{display_name} ({count})",
                callback_data=f"wgroup_{group_name}"
            )
        ])
    
    # Add "All Wallets" option
    keyboard.append([
        InlineKeyboardButton(
            text="📊 View All Wallets",
            callback_data="wgroup_all"
        )
    ])
    
    text = (
        "💼 **Your Wallet Groups**\n\n"
        f"Total wallets: {len(wallets)}\n"
        f"Groups: {len(groups)}\n\n"
        "Select a group to view details:"
    )
    
    await m.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="Markdown"
    )

@router.callback_query(F.data.startswith("wgroup_"))
async def cb_wallet_group_details(c: CallbackQuery, db_path: str, 
                                  etherscan_key: str, solscan_key: str,
                                  session: aiohttp.ClientSession,
                                  all_networks: Dict):
    """
    Show detailed view of a wallet group
    """
    group_name = c.data.replace("wgroup_", "")
    user_id = c.from_user.id
    
    # Get user's wallets
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute("SELECT * FROM wallets WHERE user_id=?", (user_id,))
        wallets = await cur.fetchall()
    
    if group_name == "all":
        selected_wallets = wallets
        display_name = "All Wallets"
    else:
        groups = group_wallets_by_name(wallets)
        selected_wallets = groups.get(group_name, [])
        display_name = group_name if group_name != "_ungrouped" else "Other Wallets"
    
    if not selected_wallets:
        await c.answer("No wallets in this group", show_alert=True)
        return
    
    # Show loading
    loading_msg = await c.message.edit_text(
        f"⏳ Loading {display_name}...\n"
        f"Fetching balances for {len(selected_wallets)} wallet(s)..."
    )
    
    # Fetch balances
    total_usd = 0
    holdings_list = []
    wallet_details = []
    
    for wallet in selected_wallets:
        wallet_id, _, network, address, label, _, _ = wallet
        
        # Get balance
        balance = await get_wallet_balance(address, network, etherscan_key, solscan_key, session)
        
        native_amount = balance['native_amount']
        usd_value = balance['usd_value']
        token_symbol = balance['token_symbol']
        
        total_usd += usd_value
        
        network_display = all_networks.get(network, get_network_display(network))
        
        holdings_list.append({
            'network': network_display,
            'amount': native_amount,
            'symbol': token_symbol,
            'usd': usd_value
        })
        
        wallet_details.append({
            'label': label,
            'network': network_display,
            'address': address,
            'amount': native_amount,
            'symbol': token_symbol,
            'usd': usd_value
        })
    
    # Generate image
    try:
        image_bio = await generate_wallet_image(display_name, total_usd, holdings_list)
        
        # Send image
        await c.message.answer_photo(
            photo=image_bio,
            caption=f"💼 **{display_name}**\n\n"
                   f"💰 Total Value: **${total_usd:,.2f}**\n"
                   f"📊 Networks: {len(holdings_list)}"
        )
    except Exception as e:
        print(f"Error generating image: {e}")
    
    # Build detailed text message
    text = f"💼 **{display_name}**\n"
    text += "━" * 36 + "\n\n"
    text += f"💰 **Total Value:** ${total_usd:,.2f}\n"
    text += f"📊 **Networks:** {len(holdings_list)}\n\n"
    
    text += "**Holdings:**\n\n"
    
    for detail in wallet_details:
        text += f"🔹 **{detail['label']}**\n"
        text += f"   🌐 {detail['network']}\n"
        text += f"   📍 `{detail['address'][:10]}...{detail['address'][-8:]}`\n"
        text += f"   💎 {detail['amount']:.6f} {detail['symbol']}\n"
        text += f"   💵 ${detail['usd']:,.2f}\n\n"
    
    # Keyboard
    keyboard = [
        [InlineKeyboardButton(text="🔙 Back to Groups", callback_data="wgroup_back")],
        [InlineKeyboardButton(text="🔄 Refresh", callback_data=f"wgroup_{group_name}")],
    ]
    
    await loading_msg.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="Markdown"
    )
    
    await c.answer()

@router.callback_query(F.data == "wgroup_back")
async def cb_back_to_groups(c: CallbackQuery, db_path: str):
    """Go back to wallet groups list"""
    user_id = c.from_user.id
    
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute("SELECT * FROM wallets WHERE user_id=?", (user_id,))
        wallets = await cur.fetchall()
    
    groups = group_wallets_by_name(wallets)
    
    keyboard = []
    
    sorted_groups = sorted(
        [(k, v) for k, v in groups.items() if k != "_ungrouped"],
        key=lambda x: x[0]
    )
    
    if "_ungrouped" in groups:
        sorted_groups.append(("_ungrouped", groups["_ungrouped"]))
    
    for group_name, group_wallets in sorted_groups:
        if group_name == "_ungrouped":
            display_name = "🔹 Other Wallets"
        else:
            display_name = f"💼 {group_name}"
        
        count = len(group_wallets)
        
        keyboard.append([
            InlineKeyboardButton(
                text=f"{display_name} ({count})",
                callback_data=f"wgroup_{group_name}"
            )
        ])
    
    keyboard.append([
        InlineKeyboardButton(
            text="📊 View All Wallets",
            callback_data="wgroup_all"
        )
    ])
    
    text = (
        "💼 **Your Wallet Groups**\n\n"
        f"Total wallets: {len(wallets)}\n"
        f"Groups: {len(groups)}\n\n"
        "Select a group to view details:"
    )
    
    await c.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="Markdown"
    )
    
    await c.answer()

# ===================================================== 
# INTEGRATION HELPER
# ===================================================== 

def setup_wallet_groups(dp, db_path: str, etherscan_key: str, 
                       solscan_key: str, session: aiohttp.ClientSession,
                       all_networks: Dict):
    """
    Setup wallet groups feature
    
    Call this from your main.py:
    
    from wallet_groups import setup_wallet_groups
    
    setup_wallet_groups(dp, DB, ETHERSCAN_API_KEY, SOLSCAN_API_KEY, session, ALL_NETWORKS)
    """
    
    # Register handlers with dependencies
    @router.message(Command("wallet"))
    async def cmd_wallet_wrapper(m: Message):
        await cmd_wallet_groups(m, db_path, etherscan_key, solscan_key, session)
    
    @router.callback_query(F.data.startswith("wgroup_"))
    async def cb_wallet_group_wrapper(c: CallbackQuery):
        await cb_wallet_group_details(c, db_path, etherscan_key, solscan_key, session, all_networks)
    
    @router.callback_query(F.data == "wgroup_back")
    async def cb_back_wrapper(c: CallbackQuery):
        await cb_back_to_groups(c, db_path)
    
    dp.include_router(router)
    
    print("✅ Wallet Groups feature enabled")