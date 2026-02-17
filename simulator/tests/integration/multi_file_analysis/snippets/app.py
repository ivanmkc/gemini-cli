import constants

def connect_to_api():
    # TODO: Update the version from the hardcoded v1 to the one in constants.py
    print("Connecting using API version v1.0.0")
    
def get_config():
    return {
        "retry": 3 # This should match MIN_RETRY_COUNT in constants.py
    }
