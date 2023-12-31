import numpy as np
import pandas as pd
import os
from torch.utils.data import DataLoader, Dataset, random_split
import torch
from typing import Union
from scipy.sparse import (random, 
                          coo_matrix,
                          csr_matrix, 
                          csr_array,
                          vstack)
from tqdm import tqdm
import pickle
from scipy.sparse import csr_matrix
from sklearn.model_selection import train_test_split
from sklearn import preprocessing 
from sklearn.cluster import KMeans


os.chdir("/Users/karol/Desktop/Antwerp/ai_project/")
ARTICLES_PATH = "/Users/karol/Desktop/Antwerp/ai_project/data/articles.csv"
CUSTOMER_PATH = "/Users/karol/Desktop/Antwerp/ai_project/data/customers.csv"
TRANSACTION_PATH = "/Users/karol/Desktop/Antwerp/ai_project/data/transactions_train.csv"

#######################################################################################
#                                 Data Transformations                                #
#######################################################################################
def data_preprocessing(feature_generation=False, return_encodings=False, save=False):
    '''
    Responsible for preprocessing the data. It includes opreations such as article encoding or customers encodings. Also handles missing data. 
    There is also function which does some basic feature engineering based on the feature_engineering.ipynb file but ultimately it is not used.
    Please adjust the paths stated above for required dataframes.
    Args:
        feature_generation: boolean indicating whether to perform feature engineering or not
        return_encodings: boolean indicating whether to return the encodings or not
        save: boolean indicating whether to save preprocessed dataframes and encodings
    Returns:
        transactions: preprocessed transactions dataframe
        customers: preprocessed customers dataframe
        articles: preprocessed articles dataframe
        article_encodings: dictionary of article encodings
        customer_encodings: dictionary of customer encodings
        article_decodings: dictionary of article decodings
        customer_decodings: dictionary of customer decodings
    '''
    customers = pd.read_csv(CUSTOMER_PATH)
    transactions = pd.read_csv(TRANSACTION_PATH)
    articles = pd.read_csv(ARTICLES_PATH)
    transactions["t_dat"] = pd.to_datetime(transactions["t_dat"])
    

    # ARTICLE PREPROCESSING
    # article encodings
    articles = articles[['article_id'] + list(articles.select_dtypes(include=['object']).columns)]
    articles = articles.drop(columns=["detail_desc","index_code"])

    article_encodings = {}
    article_decodings = {}
    for column in articles.columns:
        names = articles[column].unique()
        encoders = np.arange(len(names))
        article_encodings[column] = dict(zip(names, encoders))
        article_decodings[column] = dict(zip(encoders, names))
        articles[column] = articles[column].apply(lambda x: article_encodings[column][x])
    # article feature selection
    cols_to_delete = ["prod_name","product_group_name","colour_group_name","perceived_colour_value_name","perceived_colour_value_name","index_group_name"]
    articles = articles.drop(columns=cols_to_delete)
    
    # CUSTOMER PREPROCESSING
    # filing NAs
    customers.FN = customers.FN.fillna(-1)
    customers.Active = customers.Active.fillna(-1)
    age_median = np.median(customers["age"].dropna())
    customers.age = customers.age.fillna(age_median)

    # customer encodings
    customer_cols = ["customer_id","club_member_status","fashion_news_frequency","postal_code"]
    customers = customers.fillna(-1)
    customer_encodings = {}
    customer_decodings = {}
    for column in customers[customer_cols]:
        names = customers[column].unique()
        if -1 in names:
            names = names[names != -1]
            encoders = np.arange(len(names))
            customer_encodings[column] = dict(zip(names, encoders))
            customer_encodings[column][-1] = -1
        else:
            encoders = np.arange(len(names))
            customer_encodings[column] = dict(zip(names, encoders))
        customer_decodings[column] = dict(zip(encoders, names))
        
        customers[column] = customers[column].apply(lambda x: customer_encodings[column][x])
    
    # TRANSACTIONS PREPROCESSING
    transactions["t_dat"] = pd.to_datetime(transactions["t_dat"])
    transactions["customer_id"] = transactions["customer_id"].apply(lambda x: customer_encodings["customer_id"][x])
    transactions["article_id"] = transactions["article_id"].apply(lambda x: article_encodings["article_id"][x])

    # FEATURE GENERATION
    if feature_generation:
        # average price
        avg_price = pd.DataFrame(transactions.groupby("customer_id")["price"].mean().rename("avg_price"), columns=["avg_price"])
        transactions = transactions.merge(avg_price, on="customer_id", how="inner") 
        
        # article selling ranking in a given month and year
        grouped_counts = transactions.groupby(["year","month","article_id"])["article_id"].count()
        articles_rank = grouped_counts.groupby(["year", "month"]).rank(ascending=False)
        articles_rank = articles_rank.rename("top_articles")
        transactions = transactions.merge(articles_rank, how="left", on=["article_id","year","month"])

        # discount
        transactions.sort_values(by=['article_id', 't_dat'], inplace=True)
        transactions['prev_price'] = transactions.groupby('article_id')['price'].shift(1)
        # Calculate the price differences
        transactions['price_diff'] = transactions['price'] - transactions['prev_price']

        transactions = transactions.drop(columns=["prev_price", "year", "month"])
        transactions["price_diff"] = transactions["price_diff"].fillna(0)
        transactions["price_diff"] = transactions["price_diff"].apply(lambda x: 1 if x < 0 else 0)
        transactions = transactions.sort_index()
    
    if save:
        transactions.to_csv("data/preprocessed/transactions.csv", index=False)
        articles.to_csv("data/preprocessed/articles.csv", index=False)
        customers.to_csv("data/preprocessed/customers.csv", index=False)

        with open("data/preprocessed/articles_encoding.pickle", "wb") as pickle_file:
            pickle.dump(article_encodings, pickle_file)
        
        with open("data/preprocessed/customers_encoding.pickle", "wb") as pickle_file:
            pickle.dump(customer_encodings, pickle_file)

        with open("data/preprocessed/articles_decoding.pickle", "wb") as pickle_file:
            pickle.dump(article_decodings, pickle_file)
        
        with open("data/preprocessed/customers_decoding.pickle", "wb") as pickle_file:
            pickle.dump(customer_decodings, pickle_file)


    if return_encodings:
        return transactions, articles, customers, article_encodings, customer_encodings, article_decodings, customer_decodings
    else:
        return transactions, articles, customers

def customer_buckets(transactions, train_test=True):
    '''
    Responsible for creating customer buckets.
    Args:
        transactions: transactions dataframe
        train_test: boolean indicating whether to split the dataset into train and test or not
    Returns:
        customer_buckets: dictionary of customers buckets
    '''
    # last purchase for customer
    if train_test:
        customer_last_purchase = transactions.groupby('customer_id')['t_dat'].max()
        merged = transactions.merge(customer_last_purchase, on='customer_id', suffixes=('', '_last_purchase'))
        # filter train and test dataset
        train_transactions = merged[merged['t_dat'] != merged['t_dat_last_purchase']]
        test_transactions = merged[merged['t_dat'] == merged['t_dat_last_purchase']]

        # get baskets
        train_buckets = train_transactions.groupby("customer_id")["article_id"].apply(list).to_dict()
        test_buckets = test_transactions.groupby("customer_id")["article_id"].apply(list).to_dict()

        return train_buckets, test_buckets
    else:
        customer_buckets = transactions.groupby("customer_id")["article_id"].apply(list).to_dict()
        return customer_buckets

def split_transactions(transactions):
    '''
    Helper for splitting transactions to create train and validation transactions. The last bought products are considered as a validation set.
    Args:
        transactions: transactions dataframe
    Returns:
        x_transactions: train transactions dataframe
        y_transactions: validation transactions dataframe
    '''
    customer_last_purchase = transactions.groupby('customer_id')['t_dat'].max()
    merged = transactions.merge(customer_last_purchase, on='customer_id', suffixes=('', '_last_purchase'))
    # filter train and test dataset
    x_transactions = merged[merged['t_dat'] != merged['t_dat_last_purchase']]
    y_transactions = merged[merged['t_dat'] == merged['t_dat_last_purchase']]
    return x_transactions, y_transactions

def matrix_representation(transactions, train_test=True):
    '''
    Responsible for creating customer buckets and represensting as a matrix where rows represent customers and columns articles.
    Args:
        transactions: transactions dataframe
        train_test: boolean indicating whether to split the dataset into train and test or not
    Returns:
        x_mattrix: np.array of shape (customer_size, article_size) representing training transactions
        y_transactions: np.array of shape (customer_size, article_size) representing validation transactions
    '''
    customer_size = np.max(transactions['customer_id'])+1
    article_size = 105542
    if train_test:
        # filter train and test dataset
        x_transactions, y_transactions = split_transactions(transactions)

        # Get X matrix
        # Create the data array filled with ones
        data = np.ones_like(x_transactions.index)

        # Create the CSR matrix directly
        # assume that we investigate the purchase history therefore some articles were bought multiple times
        x_matrix = csr_matrix((data, 
                               (np.array(x_transactions['customer_id']), np.array(x_transactions['article_id']))), 
                               shape=(customer_size, article_size))

        # Get Y matrix
        # Create the data array filled with ones
        data = np.ones_like(y_transactions.index)

        # Create the CSR matrix directly
        y_matrix = csr_matrix((data, 
                               (np.array(y_transactions['customer_id']), np.array(y_transactions['article_id']))), 
                                shape=(customer_size, article_size))
        # as an output we are interested if the article was bought not its amount
        y_matrix[y_matrix>1]=1
        return x_matrix, y_matrix
    else:
        # Get test matrix
        # Create the data array filled with ones
        data = np.ones_like(transactions.index)

        # Create the CSR matrix directly
        matrix = csr_matrix((data, 
                            (np.array(transactions['customer_id']), np.array(transactions['article_id']))), 
                            shape=(customer_size, article_size))

        return matrix

def create_random_candidates(transactions, save_dir=None, num_sample=30_000_000):
    '''
    Responsible for creating negative samples using random candidates.
    Args:
        transactions: transactions dataframe
        save_dir: path to save the dataframe
        num_sample: number of negative samples
    Returns:
        shuffled_df: shuffled dataframe representing transactions with negative samples
    '''
    # get unique customers and articles
    unique_customers = transactions['customer_id'].unique()
    unique_articles = transactions['article_id'].unique()
    # select random customers and articles
    random_cust = np.random.choice(unique_customers, num_sample)
    random_articles = np.random.choice(unique_articles, num_sample)
    # get negative candidates dataframe
    negative_samples_df = pd.DataFrame(zip(random_cust, random_articles), columns=["customer_id","article_id",])
    # delete duplicates from original dataset
    unique_pairs = set(zip(transactions['customer_id'], transactions['article_id']))
    filtered_df = negative_samples_df[~negative_samples_df.apply(lambda row: (row['customer_id'], row['article_id']) in unique_pairs, axis=1)].copy()
    # set purchased variable
    filtered_df["purchased"] = np.zeros(len(filtered_df))
    transactions["purchased"] = np.ones(len(transactions))
    # merge dataframes
    merge = pd.concat([transactions[["customer_id","article_id", "purchased"]],filtered_df[["customer_id","article_id", "purchased"]]])
    # return shuffled dataframe
    shuffled_df = merge.sample(frac=1).reset_index(drop=True)
    if save_dir != None:
        shuffled_df.to_csv(save_dir)
    return shuffled_df

def articles_embbedings():
    '''
    Responsible for creating article embeddings.
    '''
    # read article and customer data
    articles = pd.read_csv("data/preprocessed/articles.csv") 
    # set indices
    articles = articles.set_index("article_id")
    # get embedding dims
    article_cat_dim = []
    for art_col in articles.columns:
        article_cat_dim.append(len(articles[art_col].unique()))
    return article_cat_dim

#######################################################################################
#                                    Dataset Classes                                  #
#######################################################################################

class SparseDataset(Dataset):
    """
    Custom Dataset class for scipy sparse matrix
    """
    def __init__(self, data:Union[np.ndarray, coo_matrix, csr_matrix], 
                 targets:Union[np.ndarray, coo_matrix, csr_matrix], 
                 transform:bool = None):
        
        # Transform data coo_matrix to csr_matrix for indexing
        if type(data) == coo_matrix:
            self.data = data.tocsr()
        else:
            self.data = data
            
        # Transform targets coo_matrix to csr_matrix for indexing
        if type(targets) == coo_matrix:
            self.targets = targets.tocsr()
        else:
            self.targets = targets
        
        self.transform = transform # Can be removed

    def __getitem__(self, index:int):
        return self.data[index], self.targets[index]

    def __len__(self):
        return self.data.shape[0]

class DatasetMF(Dataset):
    '''
    Dataset that handles data for matrix factorization/Two Tower models.
    '''
    def __init__(self,trans:pd.DataFrame, transform:bool = None):
        self.transactions = trans

    def __getitem__(self, index:int):
        article_id = self.transactions["article_id"][index]
        customer_id = self.transactions["customer_id"][index]
        target = self.transactions["purchased"][index]
        return article_id, customer_id, target

    def __len__(self):
        return self.transactions.shape[0]

class SingleDataset(Dataset):
    '''
    Dataset that handles data for articles and customers datasets seperately.
    '''
    def __init__(self, df:csr_matrix, transform:bool = None):
        self.df = df

    def __getitem__(self, index:int):
        return self.df[index]

    def __len__(self):
        return self.df.shape[0]
    
#######################################################################################
#                                Functions for Dataloader                             #
#######################################################################################

def sparse_coo_to_tensor(coo:coo_matrix):
    """
    Transform scipy coo matrix to pytorch sparse tensor
    """
    values = coo.data
    indices = (coo.row, coo.col)
    shape = coo.shape

    i = torch.LongTensor(np.array(indices))
    v = torch.FloatTensor(values)
    s = torch.Size(shape)

    return torch.sparse_coo_tensor(i, v, s)
    
def sparse_batch_collate(batch:list): 
    """
    Collate function which to transform scipy coo matrix to pytorch sparse tensor
    """
    data_batch, targets_batch = zip(*batch)
    if type(data_batch[0]) == csr_matrix:
        data_batch = vstack(data_batch).tocoo()
        data_batch = sparse_coo_to_tensor(data_batch)
    else:
        data_batch = torch.FloatTensor(data_batch)

    if type(targets_batch[0]) == csr_matrix:
        targets_batch = vstack(targets_batch).tocoo()
        targets_batch = sparse_coo_to_tensor(targets_batch)
    else:
        targets_batch = torch.FloatTensor(targets_batch)
    return data_batch, targets_batch

def sparse_batch_collate_single(batch:list): 
    """
    Collate function which to transform scipy coo matrix to pytorch sparse tensor
    """
    data_batch = batch
    if type(data_batch[0]) == csr_matrix:
        data_batch = vstack(data_batch).tocoo()
        data_batch = sparse_coo_to_tensor(data_batch)
    else:
        data_batch = torch.FloatTensor(data_batch)
    return data_batch
    
def MF_batch_collate(batch:list): 
    """
    Collate function which to transform scipy coo matrix to pytorch sparse tensor
    """
    articles_batch, customer_batch, targets_batch = zip(*batch)
    if type(articles_batch[0]) == csr_matrix:
        data_barticles_batchatch = vstack(articles_batch).tocoo()
        articles_batch = sparse_coo_to_tensor(articles_batch)
    else:
        articles_batch = torch.FloatTensor(articles_batch)
    
    if type(customer_batch[0]) == csr_matrix:
        customer_batch = vstack(customer_batch).tocoo()
        customer_batch = sparse_coo_to_tensor(customer_batch)
    else:
        customer_batch = torch.FloatTensor(customer_batch)

    if type(targets_batch[0]) == csr_matrix:
        targets_batch = vstack(targets_batch).tocoo()
        targets_batch = sparse_coo_to_tensor(targets_batch)
    else:
        targets_batch = torch.FloatTensor(targets_batch)
    return articles_batch, customer_batch, targets_batch

#######################################################################################
#                                      Data Loaders                                   #
#######################################################################################

def load_data(transactions, train_test=True, batch_size=1000):
    '''
    Data loader used for training MLP models. It creates matrix representations of transactions. Also splits the dataset into train and validation sets.
    Uses also batches while loading. 
    Args:
        transactions: transactions dataframe
        train_test: boolean value to indicate if the dataset should be split into train and validation sets
        batch_size: batch size for the data loader
    Returns:
        train_dataloader: pytorch data loader for the train set
        val_dataloader: pytorch data loader for the validation set
    '''
    if train_test:
        # matrix representation
        x_matrix, y_matrix = matrix_representation(transactions, train_test=train_test)
        # sparse dataset
        dataset = SparseDataset(x_matrix, y_matrix)
        # split dataset
        train_size = int(0.9 * len(dataset))
        val_size = len(dataset) - train_size
        train_dataset, val_dataset = random_split(dataset,[train_size, val_size])
        # load data
        train_dataloader = DataLoader(train_dataset, batch_size=batch_size, collate_fn=sparse_batch_collate)
        val_dataloader = DataLoader(val_dataset, batch_size=batch_size, collate_fn=sparse_batch_collate)
        return train_dataloader, val_dataloader
    else:
        # matrix representation
        matrix = matrix_representation(transactions, train_test=train_test)
        # sparse dataset
        dataset = SingleDataset(matrix)
        dataloader = DataLoader(dataset, batch_size=batch_size, collate_fn=sparse_batch_collate_single)
        return dataloader

def load_data_mf(trans:pd.DataFrame, batch_size=1000):
    '''
    Data loader used for training matrix factorization models. It splits the dataset into train and validation sets.
    It uses also batches while loading. 
    Args:
        trans: transactions dataframe
        batch_size: batch size for the data loader
    Returns:
        train_dataloader: pytorch data loader for the train set
        val_dataloader: pytorch data loader for the validation set
    '''
    test_fraction = 0.1
    unique_customers = trans['customer_id'].unique()
    train_customers, test_customers = train_test_split(unique_customers, test_size=test_fraction, random_state=42)
    train_transactions = trans[trans['customer_id'].isin(train_customers)].reset_index(drop=True)
    val_transactions = trans[trans['customer_id'].isin(test_customers)].reset_index(drop=True)

    # load data
    train_dataset = DatasetMF(train_transactions)
    val_dataset = DatasetMF(val_transactions)
    train_dataloader = DataLoader(train_dataset, batch_size=batch_size, collate_fn=MF_batch_collate)
    val_dataloader = DataLoader(val_dataset, batch_size=batch_size, collate_fn=MF_batch_collate)
    return train_dataloader, val_dataloader, test_customers

def load_customers_articles(customers, articles, test_customers=[], batch_size=1000):
    '''
    Data loader used by recommender systems to generate recommendations.
    Args:
        customers: customers dataframe
        articles: articles dataframe
        test_customers: list of customers to be used for testing
        batch_size: batch size for the data loader
    Returns:
        dataloader_cust: pytorch data loader for the train set
        dataloader_art: pytorch data loader for the validation set
    '''
    if len(test_customers)!=0:
        customers = customers[test_customers]
    dataset_cust = SingleDataset(customers)
    dataset_art = SingleDataset(articles)
    dataloader_cust = DataLoader(dataset_cust, batch_size=batch_size, collate_fn=sparse_batch_collate_single)
    dataloader_art = DataLoader(dataset_art, batch_size=batch_size, collate_fn=sparse_batch_collate_single)
    return dataloader_cust, dataloader_art

#######################################################################################
#                             Customer Diversification                                #
#######################################################################################

def sales_channel_preference(customers, transactions):
    '''
    Generates sales channel preference features for customers.
    '''
    grouped = transactions.groupby(["customer_id", "sales_channel_id"])["article_id"].count()
    percentages = grouped / grouped.groupby(level=0).transform("sum")
    # create first_cahnnel feature
    first_sales_channel = percentages[percentages.index.get_level_values('sales_channel_id') == 1]
    first_sales_channel = first_sales_channel.rename("first_channel")
    customers = customers.merge(first_sales_channel, how="left", on="customer_id")
    customers["first_channel"] = customers["first_channel"].fillna(0)
    # create second_cahnnel feature
    second_sales_channel = percentages[percentages.index.get_level_values('sales_channel_id') == 2]
    second_sales_channel = second_sales_channel.rename("second_channel")
    customers = customers.merge(second_sales_channel, how="left", on="customer_id")
    customers["second_channel"] = customers["second_channel"].fillna(0)
    return customers

def favourite_colour(customers, articles, transactions, quarter=4):
    ''' Generates favourite colour features for customers for a specific quarter of the year.'''
    # get specific quarter we are interested in
    transactions["t_dat"] = pd.to_datetime(transactions["t_dat"])
    transactions["quarter"] = transactions["t_dat"].dt.quarter  
    transactions = transactions[transactions["quarter"]==quarter]
    # merge colour information
    transactions = transactions.merge(articles[["article_id","perceived_colour_master_name"]], how="left", on="article_id")
    # get favourite colors
    grouped = transactions.groupby(["customer_id","perceived_colour_master_name"])["article_id"].count()
    max_indices = grouped.groupby(level=0).idxmax()
    favourite_color = grouped.loc[max_indices]
    favourite_color = favourite_color.rename("favourite_color")
    customers = customers.merge(favourite_color, how="left", on="customer_id")
    # Fill NAs with -1 indicating customer didn't buy anythin
    customers["favourite_color"] = customers["favourite_color"].fillna(-1)
    return customers

def preferred_garment(customers, articles, transactions):
    ''' Generates preferred garment features for customers.'''
    transactions = transactions.merge(articles[["article_id","garment_group_name"]], how="left", on="article_id")
    grouped = transactions.groupby(["customer_id", "garment_group_name"])["article_id"].count()
    percentages = grouped / grouped.groupby(level=0).transform("sum")
    preferred_garment = percentages[percentages > 0.5]
    df_garment = pd.DataFrame(preferred_garment).reset_index()[["customer_id","garment_group_name"]]
    df_garment.rename(columns={"garment_group_name":"preferred_garment"}, inplace=True)
    customers = customers.merge(df_garment, how="left", on="customer_id")
    customers["preferred_garment"] = customers["preferred_garment"].fillna(-1)
    return customers

def avg_price(customers, transactions):
    '''Generates average price features for customers.'''
    avg_grouped = transactions.groupby("customer_id")["price"].mean()
    avg_grouped = avg_grouped.rename("avg_price")
    customers = customers.merge(avg_grouped, how="left", on="customer_id")
    customers["avg_price"] = customers["avg_price"].fillna(0)
    return customers
    
def amount_purchases(customers, transactions, date_thrashold="2020-08-22"):
    '''Generates amount purchases features for customers based on recent transactions.'''
    # select recent transactions
    transactions["t_dat"] = pd.to_datetime(transactions["t_dat"])
    transactions = transactions[transactions["t_dat"]>date_thrashold]
    # get counts
    grouped = transactions.groupby("customer_id")["article_id"].count()
    grouped = grouped.rename("amount_purchases")
    customers = customers.merge(grouped, how="left", on="customer_id")
    customers["amount_purchases"] = customers["amount_purchases"].fillna(0)
    return customers

def sex_kid_estimation(customers, articles, transactions):
    '''States the proportion of the sex, kid and menswear products bought by customers.'''
    transactions = transactions.merge(articles[["article_id", "index_name"]], how="left", on="article_id")
    grouped = transactions.groupby(["customer_id", "index_name"])["article_id"].count()
    percentages = grouped/grouped.groupby(level=0).transform("sum")
    # get menswear 
    manswear = percentages[percentages.index.get_level_values('index_name') == 3]
    manswear = manswear.rename("manswear")
    customers = customers.merge(manswear, how="left", on="customer_id")
    customers["manswear"] = customers["manswear"].fillna(0)
    # get ledieswear
    ladieswear = percentages[percentages.index.get_level_values('index_name').isin([0,1,4])].groupby("customer_id").sum()
    ladieswear = ladieswear.rename("ladieswear")
    customers = customers.merge(ladieswear, how="left", on="customer_id")
    customers["ladieswear"] = customers["ladieswear"].fillna(0)
    # get kids 
    kids = percentages[percentages.index.get_level_values('index_name').isin([2,6,8,9])].groupby("customer_id").sum()
    kids = kids.rename("kids")
    customers = customers.merge(kids, how="left", on="customer_id")
    customers["kids"] = customers["kids"].fillna(0)
    return customers

def customer_clustering(customers,transactions, articles):
    '''Generates customer clusters based on index name (ultimately not used).'''
    merged = transactions.merge(articles[["article_id","product_type_name","index_name","garment_group_name"]], on="article_id")

    # Get customers baskets
    customer_baskets = merged.groupby("customer_id")["index_name"].unique()

    # Create a list of unique product_type_name values across all customers
    all_unique_products = np.unique(merged["index_name"])

    # Create a numpy matrix to store the basket data
    matrix = np.zeros((len(customer_baskets), np.max(all_unique_products)+1), dtype=int)

    # Populate the matrix with 1s for each customer's products
    for i, basket in enumerate(customer_baskets):
        matrix[i, basket] = 1
    # Normalize matrix
    matrix_norm = preprocessing.normalize(matrix)
    # Set final number of clusters
    n_cluster = 35
    # Create kmeans class and predict clusters for customers
    kmeans = KMeans(n_clusters=n_cluster, n_init="auto")
    index_name_cluster = kmeans.fit_predict(matrix_norm)
    index_name_cluster = pd.DataFrame(zip(customer_baskets.keys(), index_name_cluster), columns=["customer_id","index_name_cluster"])
    # Merge dataframes
    customers = customers.merge(index_name_cluster, on="customer_id", how="left")
    return customers

def customers_diversification(customers, transactions, articles):
    '''Generates customer diversification features for customers.'''
    customers = sales_channel_preference(customers, transactions)
    customers = favourite_colour(customers, articles, transactions, quarter=4)
    customers = preferred_garment(customers, articles, transactions)
    customers = avg_price(customers, transactions)
    customers = amount_purchases(customers, transactions, date_thrashold="2020-08-22")
    customers = sex_kid_estimation(customers, articles, transactions)
    customers = customer_clustering(customers,transactions, articles)
    return customers

#######################################################################################
#                             Articles Diversification                                #
#######################################################################################

def assign_season(x):
    if x in [12,1,2]:
        return 1
    elif x in [3,4,5]:
        return 2
    elif x in [6,7,8]:
        return 3
    else:
        return 4 

def seasonal_sales(a, t):
    '''Generates seasonal sales features for articles.They represent the proportion of their sales in the specific season.'''
    # get seasons
    t["t_dat"] = pd.to_datetime(t["t_dat"])
    t["month"] = t["t_dat"].dt.month 
    # get function to apply seasons
    t["season"] = t["month"].apply(assign_season)
    grouped = t.groupby(["article_id", "season"])["customer_id"].count()
    # get percentages
    percentages = grouped / grouped.groupby(level=0).transform("sum")
    # create winter sale var
    winter_sale = percentages[percentages.index.get_level_values('season') == 1]
    winter_sale = winter_sale.rename("winter_sale")
    a = a.merge(winter_sale, how="left", on="article_id")
    a["winter_sale"] = a["winter_sale"].fillna(0)
    # create spring sale var
    spring_sale = percentages[percentages.index.get_level_values('season') == 2]
    spring_sale = spring_sale.rename("spring_sale")
    a = a.merge(spring_sale, how="left", on="article_id")
    a["spring_sale"] = a["spring_sale"].fillna(0)
    # create summer sale var
    summer_sale = percentages[percentages.index.get_level_values('season') == 3]
    summer_sale = summer_sale.rename("summer_sale")
    a = a.merge(summer_sale, how="left", on="article_id")
    a["summer_sale"] = a["summer_sale"].fillna(0)
    # create autumn sale var
    autumn_sale = percentages[percentages.index.get_level_values('season') == 4]
    autumn_sale = autumn_sale.rename("autumn_sale")
    a = a.merge(autumn_sale, how="left", on="article_id")
    a["autumn_sale"] = a["autumn_sale"].fillna(0)
    return a

def get_avg_price(a, t):
    '''Generates the average price that product has been sold.'''
    grouped = t.groupby("article_id")["price"].mean()
    grouped = grouped.rename("avg_price")
    a = a.merge(grouped, how="left", on="article_id")
    a["avg_price"] = a["avg_price"].fillna(-1)
    return a

def seasonal_bestseller_ranking(a, t):
    '''Ranks articles based on their sales in a given season.'''
    # get seasons
    t["t_dat"] = pd.to_datetime(t["t_dat"])
    t["month"] = t["t_dat"].dt.month 
    # get function to apply seasons
    t["season"] = t["month"].apply(assign_season)
    t["year"] = t["t_dat"].dt.year 
    # Create a new DataFrame with the count of t for each (year, season, article_id) combination
    transaction_counts = t.groupby(["year", "season", "article_id"])["customer_id"].count().reset_index()
    transaction_counts.rename(columns={"customer_id": "transaction_count"}, inplace=True)

    # Create rankings within each (year, season) group based on transaction counts
    transaction_counts['article_rank'] = transaction_counts.groupby(["year", "season"])['transaction_count'].rank(ascending=False, method='dense')
    for year in transaction_counts.year.unique():
        for season in transaction_counts[transaction_counts.year==year].season.unique():
            t = transaction_counts[(transaction_counts.year==year) & (transaction_counts.season==season)]
            a = a.merge(t[["article_id","article_rank"]], how="left", on="article_id")
            a["article_rank"] = a["article_rank"].fillna(np.max(a.article_id))
            new_name = {"article_rank":"rank_"+str(season)+"_"+str(year)}
            a = a.rename(columns=new_name)
    return a

def age_articles_preference(a,t,c):
    '''Generates the age group distribution for articles.'''
    bins = [0,25,40,55,float("inf")]
    labels = ["young_preference","adult_preferences","middle_aged_preference","senior_preference"]
    c["age_group"] = pd.cut(c["age"], bins=bins, labels=labels, right=False)
    print("AGE GROUP DISTRIBUTION\n")
    print(c["age_group"].value_counts())
    t = t.merge(c[["customer_id","age_group"]], how="left", on="customer_id")
    grouped = t.groupby(["article_id", "age_group"])["customer_id"].count()
    percentages = grouped / grouped.groupby(level=0).transform("sum")
    for label in labels:
    # merge young
        preference = percentages[percentages.index.get_level_values('age_group') == label]
        preference = preference.rename(label)
        a = a.merge(preference, how="left", on="article_id")
        a[label] = a[label].fillna(0)
    return a

def articles_sales_channel(a,t):
    '''Generates sales channel distribution for articles.'''
    grouped = t.groupby(["article_id", "sales_channel_id"])["customer_id"].count()
    percentages = grouped / grouped.groupby(level=0).transform("sum")
    for channel in t["sales_channel_id"].unique():
        preference = percentages[percentages.index.get_level_values('sales_channel_id') == channel]
        name = "sales_channel_"+str(channel)
        preference = preference.rename(name)
        a = a.merge(preference, how="left", on="article_id")
        a[name] = a[name].fillna(0)
    return a

def articles_diversification(articles, transactions, customers):
    '''Generates articles diversification features for articles.'''
    articles = seasonal_sales(articles, transactions)
    articles = get_avg_price(articles, transactions)
    articles = seasonal_bestseller_ranking(articles, transactions)
    articles = age_articles_preference(articles, transactions, customers)
    articles = articles_sales_channel(articles,transactions)
    return articles

    