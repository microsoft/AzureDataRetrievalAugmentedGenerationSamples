# Samples for Retrieval-Augmented LLMs with Azure Data

This repo contains code samples and links to help you get started with retrieval augmentation generation (RAG) on Azure. 
The samples follow a RAG pattern that include the following steps:

1. Add sample data to an Azure database product
2. Create embeddings from the sample data using an Azure OpenAI Embeddings model
3. Link the Azure database product to Azure Cognitive Search (for databases without native vector indexing)
4. Create a vector index on the embeddings
5. Perform vector similarity search
6. Perform question answering over the sample data using an Azure OpenAI Completions model
   

## Resources and Coverage

Table below provides a high level guidance. Please follow the links to the relevant resources.

| Azure data product |Native vector indexing OR Azure Cognitive Search (ACS) | Guidance: repo, blog or docs| 
|----------|----------|---------------------------------------------|
|   Azure Database for PostgreSQL |      Native    | Sample in this repo (Python)|
|   CosmosDB - MongoDB vCore |    Native      | [Docs](https://learn.microsoft.com/en-us/azure/cosmos-db/mongodb/vcore/vector-search/), [Blog](https://devblogs.microsoft.com/cosmosdb/introducing-vector-search-in-azure-cosmos-db-for-mongodb-vcore/), [Repo](https://github.com/Azure/Vector-Search-AI-Assistant-MongoDBvCore), Sample in this repo (C#, Python) |
|   Azure Cache for Redis |      Native    | Sample in this repo (Python)|
|   CosmosDB - PostgreSQL  |    ACS    |                   Sample in this repo (Python)                         |
|   CosmosDB - MongoDB |    ACS      |                   Sample in this repo (C#, Python)                          |
|   CosmosDB - NoSQL  |    ACS      |                    Sample in this repo (C#, Python), [Repo](https://github.com/Azure/Vector-Search-AI-Assistant/tree/cognitive-search-vector)                          |
|   AzureSQL  |      ACS    |                      Sample in this repo (Python)                      |          |
|   Fabric OneLake  |   ACS       |            [Fabric Notebook](https://msit.powerbi.com/groups/d53590d4-b7f4-4168-816f-bd1a0a6417cd/synapsenotebooks/b37add4f-dbe7-44eb-8ed1-bfd7b2036ed9?experience=power-bi)                                 |


## Responsible AI

Microsoft is committed to the advancement of AI driven by ethical principles.
    - Learn more about [responsible use of Azure OpenAI and LLMs here](https://learn.microsoft.com/legal/cognitive-services/openai/overview?context=/azure/ai-services/openai/context/context).
    - Learn more about [responsible AI at Microsoft here](https://aka.ms/RAI).

## Maintainer

As the maintainer of this project, please make a few updates:

- Improving this README.MD file to provide a great experience
- Updating SUPPORT.MD with content about this project's support experience
- Understanding the security reporting process in SECURITY.MD
- Remove this section from the README


## Contributing

This project welcomes contributions and suggestions.  Most contributions require you to agree to a
Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us
the rights to use your contribution. For details, visit https://cla.opensource.microsoft.com.

When you submit a pull request, a CLA bot will automatically determine whether you need to provide
a CLA and decorate the PR appropriately (e.g., status check, comment). Simply follow the instructions
provided by the bot. You will only need to do this once across all repos using our CLA.

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/).
For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or
contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.

## Trademarks

This project may contain trademarks or logos for projects, products, or services. Authorized use of Microsoft 
trademarks or logos is subject to and must follow 
[Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/en-us/legal/intellectualproperty/trademarks/usage/general).
Use of Microsoft trademarks or logos in modified versions of this project must not cause confusion or imply Microsoft sponsorship.
Any use of third-party trademarks or logos are subject to those third-party's policies.
