import boto3
import json
import uuid
import base64
from datetime import datetime

def lambda_handler(event, context):
    s3 = boto3.client('s3')
    textract = boto3.client('textract')
    comprehend = boto3.client('comprehend')
    dynamodb = boto3.resource('dynamodb')
    ses = boto3.client('ses', 
                       region_name='ap-south-1')
    
    bucket_name = 'smartsort-anshul'
    sender_email = 'anshul200307@gmail.com'
    table = dynamodb.Table('smartsort-audit-log')
    
    # API Gateway se data lo
    body = json.loads(event.get('body', '{}'))
    file_name = body.get('file_name', 'unknown')
    file_data = body.get('file_data', '')
    user_name = body.get('user_name', 'User')
    user_email = body.get('user_email', 
                          sender_email)
    
    # File S3 mein save karo
    file_bytes = base64.b64decode(file_data)
    s3.put_object(
        Bucket=bucket_name,
        Key=file_name,
        Body=file_bytes
    )
    
    file_extension = file_name.split('.')[-1].lower()
    category = 'unknown-documents'
    detected_type = 'Unknown Document'
    
    try:
        # Image check
        if file_extension in ['jpg','jpeg',
                              'png','gif']:
            category = 'image-documents'
            detected_type = 'Image Document'
            
        else:
            # Textract se text nikalo
            textract_response = \
                textract.detect_document_text(
                Document={
                    'S3Object': {
                        'Bucket': bucket_name,
                        'Name': file_name
                    }
                }
            )
            
            extracted_text = ''
            for block in textract_response['Blocks']:
                if block['BlockType'] == 'LINE':
                    extracted_text += \
                        block['Text'] + ' '
            
            if extracted_text:
                # PII detect karo
                pii_response = \
                    comprehend.detect_pii_entities(
                    Text=extracted_text[:4000],
                    LanguageCode='en'
                )
                
                pii_types = [
                    e['Type'] 
                    for e in pii_response['Entities']
                ]
                
                # Financial keywords
                financial_keywords = [
                    'invoice','receipt','bank',
                    'statement','payment',
                    'amount','transaction','balance'
                ]
                
                is_financial = any(
                    kw in extracted_text.lower() 
                    for kw in financial_keywords
                )
                
                # Category decide
                if any(p in pii_types for p in [
                    'AADHAAR','PAN',
                    'PASSPORT_NUMBER','SSN',
                    'CREDIT_DEBIT_NUMBER'
                ]):
                    category = 'pii-documents'
                    detected_type = 'PII Document'
                    
                elif is_financial:
                    category = 'financial-documents'
                    detected_type = \
                        'Financial Document'
                    
                else:
                    category = 'text-documents'
                    detected_type = 'Text Document'
                    
    except Exception as e:
        category = 'unknown-documents'
        detected_type = 'Unknown Document'
    
    # File sahi folder mein move karo
    new_key = f"{category}/{file_name}"
    s3.copy_object(
        CopySource={
            'Bucket': bucket_name, 
            'Key': file_name
        },
        Bucket=bucket_name,
        Key=new_key
    )
    s3.delete_object(
        Bucket=bucket_name, 
        Key=file_name
    )
    
    # Timestamp
    timestamp = datetime.now().strftime(
        '%Y-%m-%d %H:%M:%S'
    )
    
    # DynamoDB log
    table.put_item(
        Item={
            'file_id': str(uuid.uuid4()),
            'file_name': file_name,
            'document_type': detected_type,
            'category': category,
            'user_name': user_name,
            'user_email': user_email,
            'timestamp': timestamp,
            'status': 'Classified'
        }
    )
    
    # Email bhejo
    ses.send_email(
        Source=sender_email,
        Destination={
            'ToAddresses': [user_email]
        },
        Message={
            'Subject': {
                'Data': 'SmartSort Pro — '
                        'Document Classified!'
            },
            'Body': {
                'Text': {
                    'Data': f'''
Hello {user_name}!

Your document has been classified.

File Name  : {file_name}
Type       : {detected_type}
Stored In  : {category}/
Time       : {timestamp}

Thank you for using SmartSort Pro!
Powered by AWS Textract & Comprehend
                    '''
                }
            }
        }
    )
    
    return {
        'statusCode': 200,
        'headers': {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 
                'Content-Type'
        },
        'body': json.dumps({
            'message': 'Classified!',
            'type': detected_type,
            'folder': category,
            'time': timestamp
        })
    }