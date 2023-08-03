using Microsoft.Extensions.Configuration;
using CosmosRecipeGuide;
using Spectre.Console;
using Console = Spectre.Console.AnsiConsole;
using System.Net;
using CosmosRecipeGuide.Services;
using System.Net.Quic;
using System.Diagnostics;
using Newtonsoft.Json;
using Azure.Search.Documents;


namespace CosmosRecipeGuide
{
    internal class Program
    {

        static CosmosDbService cosmosService=null;
        static SemanticKernelService skService =null; 
        
        //static OpenAIService openAIEmbeddingService = null;
        //static CognitiveSearchService cogSearchService = null;

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

            
            cosmosService = initCosmosDBService(config);
            

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


        private static SemanticKernelService initSKService(IConfiguration config)
        {
            string OpenAIEndpoint = config["OpenAIEndpoint"];
            string OpenAIKey = config["OpenAIKey"];
            string EmbeddingDeployment = config["OpenAIEmbeddingDeployment"];
            string CompletionsDeployment = config["OpenAIcompletionsDeployment"];

            string ACSEndpoint= config["SearchServiceEndPoint"];
            string ACSAdmiKey = config["SearchServiceAdminApiKey"];

            return new SemanticKernelService(OpenAIEndpoint, OpenAIKey, EmbeddingDeployment, CompletionsDeployment, ACSEndpoint, ACSAdmiKey);
        }


        private static CosmosDbService initCosmosDBService( IConfiguration config)
        {
            CosmosDbService cosmosService=null;

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
                    cosmosService = new CosmosDbService(endpoint, key, databaseName, containerName);

                    ctx.Status("Getting Recipe Stats");
                    recipeWithEmbedding = cosmosService.GetRecipeCountAsync(true).GetAwaiter().GetResult();
                    recipeWithNoEmbedding = cosmosService.GetRecipeCountAsync(false).GetAwaiter().GetResult();                                       
                    

                });

            AnsiConsole.MarkupLine($"We have [green]{recipeWithEmbedding}[/] vectorized recipe(s) and [red]{recipeWithNoEmbedding}[/] non vectorized recipe(s).");
            Console.WriteLine("");

            return cosmosService;

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
                   cosmosService.AddRecipesAsync(recipes).GetAwaiter().GetResult();

                   ctx.Status("Getting Updated Recipe Stats");
                   recipeWithEmbedding = cosmosService.GetRecipeCountAsync(true).GetAwaiter().GetResult();
                   recipeWithNoEmbedding = cosmosService.GetRecipeCountAsync(false).GetAwaiter().GetResult();

               });

            AnsiConsole.MarkupLine($"Uploaded [green]{recipes.Count}[/] recipe(s).We have [teal]{recipeWithEmbedding}[/] vectorized recipe(s) and [red]{recipeWithNoEmbedding}[/] non vectorized recipe(s).");
            Console.WriteLine("");

        }
        

       private static void PerformSearch(IConfiguration config)
        {
            Dictionary<string, float[]> docsToUpdate = new Dictionary<string, float[]>();

            string chatCompletion=string.Empty;

            string userQuery = Console.Prompt(
                new TextPrompt<string>("Type the recipe name or your question, hit enter when ready.")
                    .PromptStyle("teal")
            );

            
            AnsiConsole.Status()
               .Start("Processing...", ctx =>
               {
                   ctx.Spinner(Spinner.Known.Star);
                   ctx.SpinnerStyle(Style.Parse("green"));

                   if (skService == null)
                   {
                       ctx.Status("Initializing Semantic Kernel Service..");
                       skService = initSKService(config);
                   }

                   ctx.Status("Performing Vector Search..");
                   var ids= skService.SearchEmbeddingsAsync(userQuery).GetAwaiter().GetResult();

                   ctx.Status("Retriving recipe(s) from Cosmos DB (RAG pattern)..");
                   var retrivedDocs=cosmosService.GetRecipesAsync(ids).GetAwaiter().GetResult();

                   ctx.Status($"Priocessing {retrivedDocs.Count} to generate Chat Response using OpenAI Service..");

                   string retrivedReceipeNames = string.Empty;
                   
                   foreach(var recipe in retrivedDocs)
                   {
                       retrivedReceipeNames += ", " + recipe.name; //to dispay recipes submitted for Completion
                   }

                   ctx.Status($"Processing '{retrivedReceipeNames}' to generate Completion using OpenAI Service..");

                   chatCompletion = skService.GenerateCompletionAsync(userQuery, JsonConvert.SerializeObject(retrivedDocs)).GetAwaiter().GetResult();

   
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
            List<string> docsToUpdate = new List<string>();
            int recipeWithEmbedding = 0;
            int recipeWithNoEmbedding = 0;
            int recipeCount = 0;

            AnsiConsole.Status()
               .Start("Processing...", ctx =>
               {
                   ctx.Spinner(Spinner.Known.Star);
                   ctx.SpinnerStyle(Style.Parse("green"));

                   if (skService == null)
                   {
                       ctx.Status("Initializing Semantic Kernel Service..");
                       skService = initSKService(config);
                   }


                   ctx.Status("Getting recipe(s) to vectorize..");
                   var Recipes = cosmosService.GetRecipesToVectorizeAsync().GetAwaiter().GetResult();
                                      
                   foreach ( var recipe in Recipes ) 
                   {
                       recipeCount++;
                       ctx.Status($"Vectorizing Recipe# {recipeCount}..");
                       skService.SaveEmbeddingsAsync(JsonConvert.SerializeObject(recipe),recipe.id).GetAwaiter().GetResult();
                       docsToUpdate.Add(recipe.id);
                   }

                   ctx.Status($"Updating {Recipes.Count} recipe(s) in Cosmos DB for vectors..");
                   cosmosService.UpdateRecipesAsync(docsToUpdate).GetAwaiter().GetResult();

                   ctx.Status("Getting Updated Recipe Stats");
                   recipeWithEmbedding = cosmosService.GetRecipeCountAsync(true).GetAwaiter().GetResult();
                   recipeWithNoEmbedding = cosmosService.GetRecipeCountAsync(false).GetAwaiter().GetResult();

               });

            AnsiConsole.MarkupLine($"Vectorized [teal]{recipeCount}[/] recipe(s). We have [green]{recipeWithEmbedding}[/] vectorized recipe(s) and [red]{recipeWithNoEmbedding}[/] non vectorized recipe(s).");
            Console.WriteLine("");

        }

       

    }
}