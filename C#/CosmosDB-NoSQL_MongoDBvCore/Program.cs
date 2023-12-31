﻿using Microsoft.Extensions.Configuration;
using CosmosRecipeGuide;
using Spectre.Console;
using Console = Spectre.Console.AnsiConsole;
using System.Net;
using CosmosRecipeGuide.Services;
using System.Net.Quic;
using System.Diagnostics;
using Newtonsoft.Json;
using CosmosRecipeGuide.Service;
using System.Reflection.Metadata;

namespace CosmosRecipeGuide
{
    internal class Program
    {

        static CosmosDBNoSQLService cosmosNoSQLService=null;
        static OpenAIService openAIEmbeddingService = null;
        static CosmosDBMongoVCoreService cosmosMongoVCoreService = null;

        private static readonly string vectorSearchIndex = "vectorSearchIndex";

        static async Task Main(string[] args)
        {

            AnsiConsole.Write(
               new FigletText("Contoso Recipes")
               .Color(Color.Red));

            Console.WriteLine("");

            var configuration = new ConfigurationBuilder()
                .AddJsonFile("appsettings.json", optional: true, reloadOnChange: true)
                .AddJsonFile($"appsettings.{Environment.GetEnvironmentVariable("ASPNETCORE_ENVIRONMENT")}.json", optional: true);

            var config = configuration.Build();

            
            cosmosNoSQLService = initCosmosDBService(config);
            

            const string cosmosUpload = "1.\tUpload recipe(s) to Cosmos DB";
            const string vectorize = "2.\tVectorize the recipe(s) and store it in Cosmos DB";
            const string search = "3.\tAsk AI Assistant (search for a recipe by name or description, or ask a question)";
            const string exit = "4.\tExit this Application";


            while (true)
            {

                var selectedOption = AnsiConsole.Prompt(
                      new SelectionPrompt<string>()
                          .Title("Select an option to continue")
                          .PageSize(10)
                          .MoreChoicesText("[grey](Move up and down to reveal more options)[/]")
                          .AddChoices(new[] {
                            cosmosUpload,vectorize ,search, exit
                          }));


                switch (selectedOption)
                {
                    case cosmosUpload:
                        UploadRecipes(config);
                        break;
                    case vectorize:
                        GenerateEmbeddings(config);                        
                        break;
                    case search:
                        PerformSearch(config);
                        break;
                    case exit:
                        return;                        
                }
            }       
                 
        }


        private static OpenAIService initOpenAIService(IConfiguration config)
        {
            string endpoint = config["OpenAIEndpoint"];
            string key = config["OpenAIKey"];
            string embeddingDeployment = config["OpenAIEmbeddingDeployment"];
            string completionsDeployment = config["OpenAIcompletionsDeployment"];
            string maxToken = config["OpenAIMaxToken"];
            
            return new OpenAIService(endpoint, key, embeddingDeployment, completionsDeployment,maxToken);
        }


        private static CosmosDBNoSQLService initCosmosDBService( IConfiguration config)
        {
            CosmosDBNoSQLService cosmosNoSQLService=null;

            string endpoint = config["CosmosUri"];
            string key = config["CosmosKey"];
            string databaseName = config["CosmosDatabase"];
            string containerName = config["CosmosContainer"];
            
            
            int recipeWithEmbedding = 0;
            int recipeWithNoEmbedding = 0;

            AnsiConsole.Status()
                .Start("Processing...", ctx =>
                {
                    
                    ctx.Spinner(Spinner.Known.Star);
                    ctx.SpinnerStyle(Style.Parse("green"));

                    ctx.Status("Creating Cosmos DB Client ..");
                    cosmosNoSQLService = new CosmosDBNoSQLService(endpoint, key, databaseName, containerName);

                    ctx.Status("Getting Recipe Stats");
                    recipeWithEmbedding = cosmosNoSQLService.GetRecipeCountAsync(true).GetAwaiter().GetResult();
                    recipeWithNoEmbedding = cosmosNoSQLService.GetRecipeCountAsync(false).GetAwaiter().GetResult();
                                        
                    

                });

            AnsiConsole.MarkupLine($"We have [green]{recipeWithEmbedding}[/] vectorized recipe(s) and [red]{recipeWithNoEmbedding}[/] non vectorized recipe(s).");
            Console.WriteLine("");

            return cosmosNoSQLService;

        }


        private static bool  initVCoreMongoService(IConfiguration config)
        {            

            string vcoreConn = config["MongoVcoreConnection"];
            string vCoreDB = config["MongoVcoreDatabase"];
            string vCoreColl = config["MongoVcoreCollection"];
            string maxResults = config["maxVectorSearchResults"];

            cosmosMongoVCoreService = new CosmosDBMongoVCoreService(vcoreConn, vCoreDB, vCoreColl, maxResults);

            return true;
        }


        private static void UploadRecipes(IConfiguration config)
        {
            string folder = config["RecipeLocalFolder"];
            int recipeWithEmbedding = 0;
            int recipeWithNoEmbedding = 0;

            List<Recipe> recipes=null;

            AnsiConsole.Status()
               .Start("Processing...", ctx =>
               {
                   ctx.Spinner(Spinner.Known.Star);
                   ctx.SpinnerStyle(Style.Parse("green"));

                   ctx.Status("Parsing Recipe files..");
                   recipes = Utility.ParseDocuments(folder);                  
                  

                   ctx.Status($"Uploading Recipe(s)..");
                   cosmosNoSQLService.AddRecipesAsync(recipes).GetAwaiter().GetResult();

                   ctx.Status("Getting Updated Recipe Stats");
                   recipeWithEmbedding = cosmosNoSQLService.GetRecipeCountAsync(true).GetAwaiter().GetResult();
                   recipeWithNoEmbedding = cosmosNoSQLService.GetRecipeCountAsync(false).GetAwaiter().GetResult();

               });

            AnsiConsole.MarkupLine($"Uploaded [green]{recipes.Count}[/] recipe(s).We have [teal]{recipeWithEmbedding}[/] vectorized recipe(s) and [red]{recipeWithNoEmbedding}[/] non vectorized recipe(s).");
            Console.WriteLine("");

        }
        

       private static void PerformSearch(IConfiguration config)
        {
            Dictionary<string, float[]> dictEmbeddings = new Dictionary<string, float[]>();

            string chatCompletion=string.Empty;

            string userQuery = Console.Prompt(
                new TextPrompt<string>("What would you to like to cook?")
                    .PromptStyle("teal")
            );

            
            AnsiConsole.Status()
               .Start("Processing...", ctx =>
               {
                   ctx.Spinner(Spinner.Known.Star);
                   ctx.SpinnerStyle(Style.Parse("green"));

                   if (openAIEmbeddingService == null)
                   {
                       ctx.Status("Connecting to Open AI Service..");
                       openAIEmbeddingService = initOpenAIService(config);
                   }


                   if (cosmosMongoVCoreService == null)
                   {
                       ctx.Status("Connecting to Azure Cosmos DB for MongoDB vCore..");
                       initVCoreMongoService(config);

                       ctx.Status("Checking for Index in Azure Cosmos DB for MongoDB vCore..");
                       if (cosmosMongoVCoreService.CheckIndexIfExists(vectorSearchIndex) == false)
                       {
                           AnsiConsole.WriteException(new Exception("Cognitive Search Index not Found, Please Build the index first."));
                           return;
                       }
                   }

                   ctx.Status("Converting User Query to Vector..");
                   var embeddingVector = openAIEmbeddingService.GetEmbeddingsAsync(userQuery).GetAwaiter().GetResult();

                   ctx.Status("Performing Vector Search..");
                   var ids = cosmosMongoVCoreService.VectorSearchAsync(embeddingVector).GetAwaiter().GetResult();

                   ctx.Status("Retriving recipe(s) from Cosmos DB (RAG pattern)..");
                   var retrivedDocs=cosmosNoSQLService.GetRecipesAsync(ids).GetAwaiter().GetResult();

                   ctx.Status($"Priocessing {retrivedDocs.Count} to generate Chat Response  using OpenAI Service..");

                   string retrivedReceipeNames = string.Empty;
                   
                   foreach(var recipe in retrivedDocs)
                   {
                       recipe.embedding = null; //removing embedding to reduce tokens during chat completion
                       retrivedReceipeNames += ", " + recipe.name; //to dispay recipes submitted for Completion
                   }

                   ctx.Status($"Processing '{retrivedReceipeNames}' to generate Completion using OpenAI Service..");

                   (string completion, int promptTokens, int completionTokens) = openAIEmbeddingService.GetChatCompletionAsync(userQuery, JsonConvert.SerializeObject(retrivedDocs)).GetAwaiter().GetResult();
                   chatCompletion = completion;
   
               });

            Console.WriteLine("");
            Console.Write(new Rule($"[silver]AI Assistant Response[/]") { Justification = Justify.Center });
            AnsiConsole.MarkupLine(chatCompletion);
            Console.WriteLine("");
            Console.WriteLine("");
            Console.Write(new Rule($"[yellow]****[/]") { Justification = Justify.Center });
            Console.WriteLine("");

        }

        private static void GenerateEmbeddings(IConfiguration config)
        {
            Dictionary<string, float[]> dictEmbeddings = new Dictionary<string, float[]>();
            int recipeWithEmbedding = 0;
            int recipeWithNoEmbedding = 0;
            int recipeCount = 0;

            AnsiConsole.Status()
               .Start("Processing...", ctx =>
               {
                   ctx.Spinner(Spinner.Known.Star);
                   ctx.SpinnerStyle(Style.Parse("green"));

                   if (openAIEmbeddingService == null)
                   {
                       ctx.Status("Connecting to Open AI Service..");
                       openAIEmbeddingService = initOpenAIService(config);
                   }


                   if (cosmosMongoVCoreService == null)
                   {
                        ctx.Status("Connecting to VCore Mongo..");
                        initVCoreMongoService(config);
                       
                        ctx.Status("Building VCore Index..");
                        cosmosMongoVCoreService.CreateVectorIndexIfNotExists(vectorSearchIndex);                       

                   }

                   ctx.Status("Getting recipe(s) to vectorize..");
                   var Recipes = cosmosNoSQLService.GetRecipesToVectorizeAsync().GetAwaiter().GetResult();
                                      
                   foreach ( var recipe in Recipes ) 
                   {
                       recipeCount++;
                       ctx.Status($"Vectorizing Recipe# {recipeCount}..");
                       var embeddingVector=openAIEmbeddingService.GetEmbeddingsAsync(JsonConvert.SerializeObject(recipe)).GetAwaiter().GetResult();
                       recipe.embedding = embeddingVector.ToList();
                       dictEmbeddings.Add(recipe.id, embeddingVector);
                   }

                   ctx.Status($"Updating {Recipes.Count} recipe(s) in Cosmos DB for vectors..");
                   cosmosNoSQLService.UpdateRecipesAsync(dictEmbeddings).GetAwaiter().GetResult();


                   ctx.Status($"Indexing {Recipes.Count} document(s) on Azure Cosmos DB for MongoDB vCore..");
                   foreach (var recipe in Recipes)
                   {
                       cosmosMongoVCoreService.UpsertVectorAsync(recipe);
                   }

                   ctx.Status("Getting Updated Recipe Stats");
                   recipeWithEmbedding = cosmosNoSQLService.GetRecipeCountAsync(true).GetAwaiter().GetResult();
                   recipeWithNoEmbedding = cosmosNoSQLService.GetRecipeCountAsync(false).GetAwaiter().GetResult();

               });

            AnsiConsole.MarkupLine($"Vectorized [teal]{recipeCount}[/] recipe(s). We have [green]{recipeWithEmbedding}[/] vectorized recipe(s) and [red]{recipeWithNoEmbedding}[/] non vectorized recipe(s).");
            Console.WriteLine("");

        }

       

    }
}