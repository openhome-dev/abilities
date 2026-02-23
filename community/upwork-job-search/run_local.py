#!/usr/bin/env python3
"""
Local test runner for upwork-job-search ability.
This uses mock SDK classes to simulate the OpenHome environment.
"""
import asyncio
import sys
import os

# Add the ability directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker
from main import UpworkJobSearchCapability


async def main():
    print("=" * 60)
    print(" Upwork Job Search - Local Test Runner")
    print("=" * 60)
    print()
    
    # Create the worker (mock)
    worker = AgentWorker()
    
    # Register and instantiate the capability
    capability = UpworkJobSearchCapability.register_capability()
    
    # Set up the worker references
    capability.worker = worker
    capability.capability_worker = CapabilityWorker(worker)
    
    # Run the capability
    print("Starting ability...\n")
    try:
        await capability.run()
    except Exception as e:
        print(f"\n Error: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("Test runner finished")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
