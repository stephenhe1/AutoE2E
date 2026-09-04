import os
from dotenv import load_dotenv

import pymongo

load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI", os.getenv("ATLAS_URI", "mongodb://localhost:27017"))

client = pymongo.MongoClient(MONGODB_URI)
db = client.myDatabase

# action-functionality collection
action_func_db = db["action-functionality"]
func_db = db["functionality"]
