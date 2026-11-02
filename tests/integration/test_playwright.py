#!/usr/bin/env python3
"""Test script to check if Playwright is working correctly."""

import asyncio
import sys
import os

# Add backend directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))

from browser_engine.session_store import load_storage_state
from browser_engine.engines.deepseek_browser import DeepSeekBrowserAdapter

async def test_deepseek_playwright():
    print("Testing DeepSeek Playwright...")
    
    # Check if session state exists
    state = load_storage_state("deepseek")
    print(f"Session state found: {state is not None}")
    if state:
        print(f"Session state has cookies: {len(state.get('cookies', [])) > 0}")
        print(f"Session state has origins: {len(state.get('origins', [])) > 0}")
    
    # Try to create adapter
    try:
        adapter = DeepSeekBrowserAdapter()
        print("DeepSeekBrowserAdapter created successfully")
        
        # Try to check if available
        try:
            from browser_engine.browser import create_stealth_page
            page, ctx = await create_stealth_page("deepseek")
            await page.goto("https://chat.deepseek.com/", wait_until="domcontentloaded", timeout=15000)
            
            # Take a screenshot
            await page.screenshot(path="deepseek_screenshot.png")
            print("Screenshot saved to deepseek_screenshot.png")
            
            # Get page content
            content = await page.content()
            print(f"Page content length: {len(content)}")
            print(f"First 500 characters: {content[:500]}...")
            
            # Check for textarea
            textarea_count = await page.locator("textarea").count()
            print(f"Textarea count: {textarea_count}")
            
            # Check for other elements
            buttons = await page.locator("button").all()
            print(f"Button count: {len(buttons)}")
            for i, button in enumerate(buttons[:10]):
                try:
                    text = await button.inner_text()
                    print(f"Button {i}: {text}")
                except Exception:
                    pass
            
            await ctx.close()
        except Exception as e:
            print(f"Error checking DeepSeek availability: {e}")
            import traceback
            traceback.print_exc()
        
        is_available = await adapter.is_available()
        print(f"DeepSeek is available: {is_available}")
        
        # Try a simple search
        if is_available:
            result = await adapter.search("What is example.com?")
            print(f"Search completed with error: {result.error}")
            print(f"Answer: {result.answer[:100]}...")
            print(f"Citations: {len(result.citations)}")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(test_deepseek_playwright())
    finally:
        loop.close()
