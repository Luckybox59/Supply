"""
Example integration for the new lib/ architecture.

This demonstrates how to use the simplified modules in the refactored Parser.
"""

import os
from typing import List, Optional

# Import simplified modules
from lib.data_processor import process_documents
from lib.email_sender import UnifiedEmailSender
from lib.email_searcher import UnifiedEmailSearcher
from logging_setup import get_logger

logger = get_logger(__name__)


def example_document_processing():
    """
    Example of how to process documents with the new architecture.
    """
    # Example usage of the simplified data processor
    work_dir = os.getcwd()
    application_file = "application.pdf"  # Example file
    invoice_files = ["invoice1.pdf", "invoice2.xlsx"]  # Example files
    
    try:
        # Process documents using the simplified interface
        results, elapsed_time, report, output_files = process_documents(
            work_dir=work_dir,
            application_file=application_file,
            invoice_files=invoice_files,
            model="qwen/qwen-2.5-72b-instruct:free",
            use_llm_report=False
        )
        
        logger.info(f"Processed {len(results)} documents in {elapsed_time:.2f}s")
        logger.info(f"Generated files: {list(output_files.keys())}")
        
        return results, report, output_files
        
    except Exception as e:
        logger.error(f"Error processing documents: {e}")
        return [], "", {}


def example_email_operations():
    """
    Example of how to use the unified email services.
    """
    try:
        # Initialize unified email sender (automatically detects Gmail vs SMTP)
        sender = UnifiedEmailSender()
        
        # Test connection
        if sender.test_connection():
            logger.info("Email connection successful")
            
            # Send email with attachments
            success = sender.send_email(
                to_email="recipient@example.com",
                subject="Test Email",
                body="This is a test email from the refactored Parser.",
                attachments=["report.md", "results.json"],
                from_name="Parser System"
            )
            
            if success:
                logger.info("Email sent successfully")
        
        # Initialize unified email searcher
        searcher = UnifiedEmailSearcher()
        
        # Search for emails
        emails = searcher.search_emails_by_recipient(
            to_email="client@example.com",
            subject="project"
        )
        
        logger.info(f"Found {len(emails)} emails")
        
        return success, emails
        
    except Exception as e:
        logger.error(f"Error with email operations: {e}")
        return False, []


def integration_workflow_example():
    """
    Complete workflow example using the new architecture.
    """
    logger.info("Starting Parser workflow with new architecture")
    
    # Step 1: Process documents
    results, report, output_files = example_document_processing()
    
    if results:
        # Step 2: Send results via email
        success, emails = example_email_operations()
        
        if success:
            logger.info("Workflow completed successfully")
        else:
            logger.warning("Email operations failed")
    else:
        logger.error("Document processing failed")


if __name__ == "__main__":
    integration_workflow_example()