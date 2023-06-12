from datetime import datetime
import hashlib
import json
import pymongo
import bs4
from selenium import webdriver
import re


# secondary models
class MongoDocumentType:
    BUSINESS = "business"
    REVIEW = "review"

# main models
class Business:
    """
    Business of TripAdvisor
    """

    def __init__(
            self,
            business_name: str,
            business_url: str
    ):
        self.business_name = business_name
        self.business_url = business_url

    def to_mongo_document(self) -> dict:
        """
        Serialize the object as a mongo document
        """

        mongo_doc = {
            "unique_id": self.get_object_hash(),
            "type": MongoDocumentType.BUSINESS,
            "business_name": self.business_name,
            "business_url": self.business_url
        }
        return mongo_doc

    def get_object_hash(self) -> str:
        """
        Calculate the hash of the business object,
        it will be used as a custom ID in MongoDB to avoid duplicate insertions
        """
        obj_json = json.dumps(self, default=lambda o: o.__dict__, sort_keys=True)
        hash_object = hashlib.sha256(obj_json.encode())
        return hash_object.hexdigest()


class Review:
    """
    Review of a Business of TripAdvisor
    """

    def __init__(
            self,
            business: Business,
            reviewer: str = "",
            review_date: datetime.date = None,
            visit_data: datetime.date = None,
            review_title: str = "",
            review_text: str = "",
            review_rating: float = -1,
    ):
        self.business = business
        self.reviewer = reviewer
        self.review_date = review_date
        self.visit_data = visit_data
        self.review_title = review_title
        self.review_text = review_text
        self.review_rating = review_rating

    def to_mongo_document(self) -> dict:
        """
        Serialize the object as a mongo document
        """

        mongo_doc = {
            "unique_id": self.get_object_hash(),
            "type": MongoDocumentType.REVIEW,
            "reviewer": self.reviewer,
            "business_reviewed": self.business.business_name,
            "review_date": str(self.review_date),
            "review_title": self.review_title,
            "review_text": self.review_text,
            "review_rating": self.review_rating,
            "visit_data": str(self.visit_data)

        }
        return mongo_doc

    def get_object_hash(self) -> str:
        """
        Calculate the hash of the review object,
        it will be used as a custom ID in MongoDB to avoid duplicate insertions
        """
        hash_data = {
            "business": self.business.business_name,
            "reviewer": self.reviewer,
            "review_title": self.review_title,
            "review_text": self.review_text,
            "review_rating": self.review_rating,
        }
        obj_json = json.dumps(hash_data, sort_keys=True)
        hash_object = hashlib.sha256(obj_json.encode())
        return hash_object.hexdigest()


# functionality models
class TripAdvisorMongoClient:
    def __init__(
            self,
            connection_string: str = "",
            database: pymongo.database.Database or str = "",
            collection: pymongo.collection.Collection or str = "",

    ):
        self.connection_string = connection_string
        self.mongo_client = pymongo.MongoClient(self.connection_string)
        self.database = self.mongo_client[database]
        self.collection = self.database[collection]

    def insert_business(self, business: Business) -> bool:
        if self.collection.find_one({"unique_id": business.get_object_hash()}) is not None:
            return False  # document exist
        self.collection.insert_one(business.to_mongo_document())
        return True

    def insert_review(self, review: Review) -> bool:
        if self.collection.find_one({"unique_id": review.get_object_hash()}) is not None:
            return False  # document exist
        self.collection.insert_one(review.to_mongo_document())
        return True

    def get_businesses(self) -> list[dict]:
        businesses = self.collection.find({
            "type": MongoDocumentType.BUSINESS
        })

        return [{k: v for k, v in doc.items() if k not in ['_id', 'unique_id', 'type']} for doc in businesses]

    def get_reviews(self) -> list[dict]:
        reviews = self.collection.find({
            "type": MongoDocumentType.REVIEW
        })

        return [{k: v for k, v in doc.items() if k not in ['_id', 'unique_id', 'type']} for doc in reviews]

class TripAdvisorWebScrapper():
    def __init__(
            self,
            web_driver: webdriver = None,
            trip_advisor_mongo_client: TripAdvisorMongoClient = None

    ):
        if web_driver is None:
            web_driver = webdriver.Chrome()
        self.web_driver = web_driver
        self.trip_advisor_mongo_client = trip_advisor_mongo_client
        self.TRIP_ADVISOR_URL = 'https://www.tripadvisor.com'



    def get_and_store_businesses(self, start_url: str) -> list[Business]:
        next_page_arrow_class = "BrOJk u j z _F wSSLS tIqAi unMkR"
        business_class = "alPVI eNNhq PgLKC tnGGX"
        def find_next_page_arrow(current_page: bs4.BeautifulSoup) -> bs4.element.Tag or None:
            next_or_prev_arrows = current_page.find_all("a", class_=next_page_arrow_class)
            for element in next_or_prev_arrows:
                if element['aria-label'] == "Next page":
                    return element
            return None

        def get_all_business_in_page(current_page: bs4.BeautifulSoup) -> list[Business]:
            businesses_in_page = current_page.find_all("div", class_=business_class)
            business_in_page = []
            for element in businesses_in_page:
                business_in_page.append(
                    Business(
                        business_name=element.div.div.text.split('.', 1)[-1].strip(),
                        business_url=self.TRIP_ADVISOR_URL + element.a.get('href')
                    )
                )
            return business_in_page

        businesses = []
        self.web_driver.get(start_url)

        while True:
            try:
                # parse the current page
                current_page = bs4.BeautifulSoup(self.web_driver.page_source, 'html.parser')
                for business in get_all_business_in_page(current_page):
                    businesses.append(business)
                    self.trip_advisor_mongo_client.insert_business(business)

                next_page_arrow = find_next_page_arrow(current_page)

                if not next_page_arrow:
                    break  # No 'Next page' arrow found, (end of pagination)
                new_url = self.TRIP_ADVISOR_URL + next_page_arrow['href']
                self.web_driver.get(new_url)

            except Exception as e:
                print(f"An error occurred: {str(e)}")
                break

        return businesses

    def get_and_store_reviews(self, businesses: list[dict]) -> list[Review]:
        next_page_arrow_class = "BrOJk u j z _F wSSLS tIqAi unMkR"
        def get_all_reviews_in_page(current_page: bs4.BeautifulSoup,business: list[dict]) -> list[Review]:
            reviews = []
            review_cards = current_page.find_all('div', class_='_c', attrs={'data-automation': 'reviewCard'})
            for card in review_cards:
                try:
                    review_username = card.find('a', class_='BMQDV _F G- wSSLS SwZTJ FGwzt ukgoS').text
                    review_date_str = card.find('div', class_='RpeCd').text.strip()
                    review_date_str = review_date_str.split(" • ")[0]  # Remove " • Family" part
                    review_date = datetime.strptime(review_date_str, "%b %Y").date()
                    review_title = card.find('div', class_='biGQs _P fiohW qWPrE ncFvv fOtGX').text.strip()
                    review_text = card.find('div', class_='biGQs _P pZUbB KxBGd').text.strip()
                    review_element = card.find('svg', class_='UctUV d H0')
                    aria_label = review_element.get('aria-label')
                    rating_value = re.search(r'([\d.]+)\s*of', aria_label).group(1)
                    review_rating = int(float(rating_value))
                    review_visit = card.find('div', class_='TreSq').find('div', class_='biGQs _P pZUbB ncFvv osNWb').text.strip()
                    visit_date_str = review_visit.replace("Written ", "")
                    review_visit_date = datetime.strptime(visit_date_str, "%B %d, %Y").date()
                except Exception as error:
                    continue

                business_obj = Business(
                    business_name=business['business_name'],
                    business_url=business['business_url']
                )
                reviews.append(
                    Review(
                        business = business_obj,
                        reviewer = review_username,
                        review_date = review_date,
                        visit_data = review_visit_date,
                        review_title= review_title,
                        review_text= review_text,
                        review_rating= review_rating
                    )
                )

            return reviews
        def find_next_page_arrow(current_page: bs4.BeautifulSoup) -> bs4.element.Tag or None:
            next_or_prev_arrows = current_page.find_all("a", class_=next_page_arrow_class)
            for element in next_or_prev_arrows:
                if element['aria-label'] == "Next page":
                    return element
            return None

        reviews = []
        for business in businesses:
            self.web_driver.get(business['business_url'])
            while True:
                current_page = bs4.BeautifulSoup(self.web_driver.page_source, 'html.parser')
                reviews_in_current_page = get_all_reviews_in_page(current_page,business)
                for review in reviews_in_current_page:
                    self.trip_advisor_mongo_client.insert_review(review)
                    reviews.append(review)

                next_page_arrow = find_next_page_arrow(current_page)
                if not next_page_arrow:
                    break  # No 'Next page' arrow found, (end of pagination)
                new_url = self.TRIP_ADVISOR_URL + next_page_arrow['href']
                self.web_driver.get(new_url)
        return reviews
