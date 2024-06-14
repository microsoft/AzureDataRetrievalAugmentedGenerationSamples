# Use Azure Cosmos DB Mongo vCore with Langchain in Java.

This sample provides a demo showcasing the usage of the RAG pattern for integrating Azure Open AI services with custom data in Azure Cosmos DB MongoDB vCore, using langchain framework for java (https://github.com/langchain4j/langchain4j).

### Prerequisites

- Azure Cosmos DB Mongo Account
    - Connection string
- Azure Open AI Service
    - Deploy text-davinci-003 model for Embeding
    - Deploy gpt-35-turbo model for Chat Completion


### Installation
``` bash 
mvn install
```

### Run

Before running the application, you need to set environment variables. Either export them in command line or set system variables:

```bash
    export COSMOS_URI_HNSW="Cosmos DB MongoDB vCore connection string"
    export AZURE_OPENAI_ENDPOINT="endpoint for your Azure OpenAI account"
    export AZURE_OPENAI_APIKEY="key for your Azure OpenAI account"
    export AZURE_OPENAI_CHATDEPLOYMENTID="deployment id for your Azure OpenAI chat embeddings"
    export AZURE_OPENAI_EMBEDDINGDEPLOYMENTID="deployment is for your Azure OpenAI chat completions"
```

Then run the app:

```bash
mvn exec:java   
```

## Getting Started
When you run the application for the first time, it will read and vectorize docs in the `PDF_docs` folder (you can add your own pdf or txt docs here), and insert them into Cosmos DB MongoDB vCore vector store. To begin, just ask a question in command line. 

