from pymongo import MongoClient

conn = MongoClient('mongodb://localhost:27017/')
db = conn["online_shop"]
#iterates through thr collections and takes 5 samples from each 
samples_by_collection = {
	collection_name: list(db[collection_name].aggregate([{"$sample": {"size": 5}}]))
	for collection_name in db.list_collection_names()   
}





