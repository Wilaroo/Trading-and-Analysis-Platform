#!/usr/bin/env python3
"""
Test script for the new fundamental analysis functionality
"""

import sys
sys.path.append('/app/backend')

from services.investopedia_knowledge import get_investopedia_knowledge

def test_fundamental_analysis():
    """Test the new fundamental analysis methods"""
    service = get_investopedia_knowledge()
    
    print("=== Testing Fundamental Analysis Methods ===\n")
    
    # Test getting all fundamental metrics
    print("1. All fundamental metrics:")
    metrics = service.get_all_fundamental_metrics()
    print(f"Found {len(metrics)} metrics: {', '.join(metrics[:5])}...\n")
    
    # Test getting a specific metric
    print("2. P/E Ratio details:")
    pe_info = service.get_fundamental_metric("pe_ratio")
    if pe_info:
        print(f"Name: {pe_info['name']}")
        print(f"Category: {pe_info['category']}")
        print(f"Formula: {pe_info['formula']}")
        print(f"Good values: {pe_info['good_values']}\n")
    
    # Test getting valuation metrics
    print("3. Valuation metrics:")
    valuation = service.get_valuation_metrics()
    print(f"Found {len(valuation)} valuation metrics\n")
    
    # Test stock analysis
    print("4. Stock fundamental analysis example:")
    analysis = service.analyze_stock_fundamentals(
        pe=12.5,  # Good P/E
        pb=0.8,   # Below book value
        de=0.3,   # Conservative debt
        roe=0.18, # Good ROE
        peg=0.9,  # Undervalued per PEG
        fcf_positive=True
    )
    
    print(f"Value Score: {analysis['value_score']}/100")
    print(f"Assessment: {analysis['overall_assessment']}")
    print(f"Positive signals: {len(analysis['signals'])}")
    print(f"Warnings: {len(analysis['warnings'])}")
    
    if analysis['signals']:
        print("Signals:")
        for signal in analysis['signals']:
            print(f"  - {signal}")
    
    if analysis['warnings']:
        print("Warnings:")
        for warning in analysis['warnings']:
            print(f"  - {warning}")
    
    print("\n5. Fundamental analysis context for AI:")
    context = service.get_fundamental_analysis_context_for_ai()
    print(f"Context length: {len(context)} characters")
    print("Context preview:")
    print(context[:200] + "...")
    
    print("\n=== All tests completed successfully! ===")

if __name__ == "__main__":
    test_fundamental_analysis()