using System;
using System.Collections.Generic;
using System.Configuration;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using Azure;
using Azure.AI.OpenAI;
using Azure.Search.Documents;
using Azure.Search.Documents.Indexes;
using Azure.Search.Documents.Indexes.Models;
using Azure.Search.Documents.Models;
using Microsoft.Extensions.Configuration;

namespace CosmosRecipeGuide
{
    internal class CognitiveSearchService
    {
        private const string _SemanticSearchConfigName = "my-semantic-config";

        private readonly SearchIndexClient? _indexClient=null;
        private readonly SearchClient? _searchClient = null;

        private readonly string _searchIndexName =string.Empty;
        private readonly IConfiguration? _configuration =null;

        public CognitiveSearchService(IConfiguration config)
        {
            _configuration = config;
            
            _searchIndexName = _configuration["SearchIndexName"];

            _indexClient = CreateSearchIndexClient();
            _searchClient = _indexClient.GetSearchClient(_searchIndexName);
        }

        //check if the  index already exists
        public bool CheckIndexIfExists()
        {
            try
            {
                if (_indexClient.GetIndex(_searchIndexName) != null)
                {
                    return true;
                }
            }
            catch (RequestFailedException e) when (e.Status == 404)
            {
                return false;
            }

            return false;
        }

        //build the index
        public void BuildIndex()
        {
            DeleteIndexIfExists(_searchIndexName, _indexClient);
            CreateIndex(_searchIndexName, _indexClient);
        }

        // Upload documents as a batch.
        public async void UploadandIndexDocuments(List<Recipe> Recipes)
        {
            await _searchClient.IndexDocumentsAsync(IndexDocumentsBatch.Upload(ConvertRecipeToCogSarchDoc(Recipes)));
            
        }

        //Reducing the number of attributes in the class
        private List<CogSearchDoc> ConvertRecipeToCogSarchDoc(List<Recipe> recipes)
        {
            List<CogSearchDoc> cogSearchdocs=new List<CogSearchDoc>();
            foreach (Recipe recipe in recipes)
            {
                CogSearchDoc cdoc=new CogSearchDoc();
                cdoc.id = recipe.id;
                cdoc.name = recipe.name;
                cdoc.description = recipe.description;  
                cdoc.embedding  = recipe.embedding;

                cogSearchdocs.Add(cdoc);
            }

            return cogSearchdocs;
        }


        internal async Task<List<string>> SingleVectorSearch(float[] queryEmbeddings, int searchCount = 5)
        {

            // Perform the vector similarity search  
            var vector = new SearchQueryVector { K = 3, Fields = "embedding", Value = queryEmbeddings.ToArray() };
            var searchOptions = new SearchOptions
            {
                Vector = vector,
                Size = searchCount,
                Select = { "id"},
            };

            SearchResults<SearchDocument> response = await _searchClient.SearchAsync<SearchDocument>(null, searchOptions);

            List<string> ids = new List<string>();
            await foreach (SearchResult<SearchDocument> result in response.GetResultsAsync())
            {
                ids.Add(result.Document["id"].ToString());    
            }
            return ids; 
        }



        private SearchIndexClient CreateSearchIndexClient()
        {
            string searchServiceEndPoint = _configuration["SearchServiceEndPoint"];
            string adminApiKey = _configuration["SearchServiceAdminApiKey"];

            SearchIndexClient _indexClient = new SearchIndexClient(new Uri(searchServiceEndPoint), new AzureKeyCredential(adminApiKey));
            return _indexClient;
        }

        private SearchClient CreateSearchClientForQueries(string indexName)
        {
            string searchServiceEndPoint = _configuration["SearchServiceEndPoint"];
            string queryApiKey = _configuration["SearchServiceQueryApiKey"];

            SearchClient _searchClient = new SearchClient(new Uri(searchServiceEndPoint), indexName, new AzureKeyCredential(queryApiKey));
            return _searchClient;
        }

              
        private void DeleteIndexIfExists(string indexName, SearchIndexClient _indexClient)
        {
            try
            {
                if (_indexClient.GetIndex(indexName) != null)
                {
                    _indexClient.DeleteIndex(indexName);
                }
            }
            catch (RequestFailedException e) when (e.Status == 404)
            {
                return;
            }
        }

        private void CreateIndex(string indexName, SearchIndexClient _indexClient)
        {
            _indexClient.CreateOrUpdateIndex(BuildVectorSearchIndex(indexName));
        }

        internal SearchIndex BuildVectorSearchIndex(string name)
        {
            string vectorSearchConfigName = "my-vector-config";

            SearchIndex searchIndex = new(name)
            {
                VectorSearch = new()
                {
                    AlgorithmConfigurations =
                {
                    new VectorSearchAlgorithmConfiguration(vectorSearchConfigName, "hnsw")
                }
                },
                SemanticSettings = new()
                {

                    Configurations =
                    {
                       new SemanticConfiguration(_SemanticSearchConfigName, new()
                       {
                           TitleField = new(){ FieldName = "name" },
                           ContentFields =
                           {
                               new() { FieldName = "description" }
                           }
                       })

                },
                },
                Fields =
            {
                new SimpleField("id", SearchFieldDataType.String) { IsKey = true, IsFilterable = true, IsSortable = true, IsFacetable = true },
                new SearchableField("name") { IsFilterable = true, IsSortable = true },
                new SearchableField("description") { IsFilterable = true },
                new SearchField("embedding", SearchFieldDataType.Collection(SearchFieldDataType.Single))
                {
                    IsSearchable = true,
                    Dimensions = 1536,
                    VectorSearchConfiguration = vectorSearchConfigName
                }
            }
            };
            return searchIndex;
        }
         
    }
}
